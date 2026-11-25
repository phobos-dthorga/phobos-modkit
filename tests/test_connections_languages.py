"""The Code map's TypeScript, Svelte and Rust readers, and the window's asks joined to the host's commands (1.128.0), on a made-up
repository shaped like a Tauri program: no code of anyone's."""
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import connections
from phobos_modkit.connections import rustcode, webcode

CLIENT = """import { ask } from "../shell/desktopClient";
import type { Failed } from "../shell/types";

// a comment naming readSetup( must not count
export async function readSetup(): Promise<string> {
  return ask<string, string>("setup_status", {}, (x) => x);
}

export const lookAgain = async () => {
  return ask("setup_look_again", {});
};
"""

SHELL = """export async function ask<T>(command: string, args: unknown): Promise<T> {
  return invoke(command, args);
}
"""

PANEL = """<script lang="ts">
  import { readSetup } from "./desktopClient";
  import Child from "./Child.svelte";

  async function load() {
    await readSetup();
  }
</script>

<section>
  <Child />
  <button onclick={() => void load()}>Load</button>
</section>
"""

CHILD = """<script lang="ts">
  let { name }: { name: string } = $props();
</script>
<p>{name}</p>
"""

LIB = """mod setup_page;

/// How the setup stands.
#[tauri::command]
async fn setup_status() -> Result<String, String> {
    setup_page::read()
}

#[tauri::command]
fn setup_look_again() -> String {
    // "a quote in a comment" must not hide what follows
    setup_page::look_again()
}

fn helper() {}
"""

PAGE = """pub struct Setup {
    pub rows: Vec<String>,
}

impl Setup {
    pub fn empty() -> Self {
        Setup { rows: Vec::new() }
    }
}

pub fn read() -> Result<String, String> {
    let _ = Setup::empty();
    Ok(format!("{}", "x"))
}

pub fn look_again() -> String {
    read().unwrap_or_default()
}
"""


class LanguagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        files = {"src/lib/setup/desktopClient.ts": CLIENT, "src/lib/shell/desktopClient.ts": SHELL,
                 "src/lib/setup/Panel.svelte": PANEL, "src/lib/setup/Child.svelte": CHILD,
                 "src-tauri/src/lib.rs": LIB, "src-tauri/src/setup_page.rs": PAGE}
        for relative, text in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.graph = connections.read_graph(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def edges(self, kind):
        return {(e.source, e.target) for e in self.graph.edges if e.kind == kind}

    def test_typescript_functions_imports_and_calls(self):
        nodes = self.graph.nodes
        self.assertIn("ts:src/lib/setup/desktopClient.ts:readSetup", nodes)
        self.assertIn("ts:src/lib/setup/desktopClient.ts:lookAgain", nodes)
        self.assertEqual(nodes["ts:src/lib/setup/desktopClient.ts:readSetup"].line, 5)
        imports = self.edges("imports")
        self.assertIn(("ts:file:src/lib/setup/desktopClient.ts", "ts:file:src/lib/shell/desktopClient.ts"), imports)
        self.assertIn(("ts:src/lib/setup/desktopClient.ts:readSetup", "ts:src/lib/shell/desktopClient.ts:ask"),
                      self.edges("calls"))

    def test_a_svelte_component_uses_what_it_names_and_calls_what_it_imported(self):
        self.assertEqual(self.graph.nodes["ts:file:src/lib/setup/Panel.svelte"].kind, "component")
        self.assertIn(("ts:file:src/lib/setup/Panel.svelte", "ts:file:src/lib/setup/Child.svelte"), self.edges("uses"))
        self.assertIn(("ts:src/lib/setup/Panel.svelte:load", "ts:src/lib/setup/desktopClient.ts:readSetup"), self.edges("calls"))

    def test_rust_functions_types_impls_modules_and_calls(self):
        nodes = self.graph.nodes
        self.assertIn("rs:src-tauri/src/setup_page.rs:Setup::empty", nodes)
        self.assertEqual(nodes["rs:src-tauri/src/setup_page.rs:Setup"].kind, "type")
        self.assertEqual(nodes["rs:src-tauri/src/lib.rs:setup_status"].end, 7)
        self.assertIn(("rs:file:src-tauri/src/lib.rs", "rs:file:src-tauri/src/setup_page.rs"), self.edges("holds"))
        calls = self.edges("calls")
        self.assertIn(("rs:src-tauri/src/setup_page.rs:read", "rs:src-tauri/src/setup_page.rs:Setup::empty"), calls)
        self.assertIn(("rs:src-tauri/src/lib.rs:setup_look_again", "rs:src-tauri/src/setup_page.rs:look_again"), calls)

    def test_the_window_s_asks_are_joined_to_the_host_s_commands(self):
        self.assertEqual(rustcode.commands(self.root), {
            "setup_status": "rs:src-tauri/src/lib.rs:setup_status",
            "setup_look_again": "rs:src-tauri/src/lib.rs:setup_look_again"})
        calls = self.edges("calls")
        self.assertIn(("ts:src/lib/setup/desktopClient.ts:readSetup", "rs:src-tauri/src/lib.rs:setup_status"), calls)
        self.assertIn(("ts:src/lib/setup/desktopClient.ts:lookAgain", "rs:src-tauri/src/lib.rs:setup_look_again"), calls)
        self.assertTrue(any(r["language"] == "window to host" for r in self.graph.readers))

    def test_declared_in_gives_each_thing_s_lines(self):
        rust = rustcode.declared_in(PAGE, "a.rs")
        self.assertIn(("rs:a.rs:Setup::empty", 6, 8), rust)
        web = webcode.declared_in(CLIENT, "c.ts")
        self.assertEqual(web[0], ("ts:c.ts:readSetup", 5, 8))


if __name__ == "__main__":
    unittest.main()
