"""The kit's compiled tools: where to find them and how to build them.

The Rust tools build with cargo into a folder outside the repository by default (%LOCALAPPDATA%\\phobos-modkit\\target
on Windows, ~/.cache/phobos-modkit/target elsewhere): a Rust build folder runs to hundreds of megabytes and should
not sit in a cloud-synced folder. A build in the repository's own target folder (as CI makes) is found too.

Tools an installer brought ready-built (`programs bundle`, 1.62.0) are found first: in PHOBOS_MODKIT_TOOLS, else a `tools`
folder beside the kit's package folder, as D'thorga Companion's installer lays them out.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

KIT_ROOT = Path(__file__).resolve().parents[2]
ENV_VARS = {"xml-index": "PHOBOS_XML_INDEX"}  # name -> environment variable that points at the program
BUILD_ENV = "PHOBOS_MODKIT_BUILD"            # overrides the build folder
BUNDLED_ENV = "PHOBOS_MODKIT_TOOLS"          # a folder of ready-built tools, instead of the one beside the kit


class ToolMissing(RuntimeError):
    pass


def program_name(name, platform=None):
    return f"{name}.exe" if (platform or sys.platform) == "win32" else name


def build_dir(environ=None, platform=None, home=None):
    """Where cargo builds the kit's tools: PHOBOS_MODKIT_BUILD, else a per-user folder outside any repository."""
    environ = os.environ if environ is None else environ
    if environ.get(BUILD_ENV):
        return Path(environ[BUILD_ENV])
    if (platform or sys.platform) == "win32" and environ.get("LOCALAPPDATA"):
        base = Path(environ["LOCALAPPDATA"])
    else:
        base = Path(environ["XDG_CACHE_HOME"]) if environ.get("XDG_CACHE_HOME") else \
            (Path.home() if home is None else Path(home)) / ".cache"
    return base / "phobos-modkit" / "target"


def bundled_dir(environ=None, root=KIT_ROOT):
    """Where an installer put the kit's tools ready-built: PHOBOS_MODKIT_TOOLS, else `tools` beside the kit's package folder."""
    environ = os.environ if environ is None else environ
    return Path(environ[BUNDLED_ENV]) if environ.get(BUNDLED_ENV) else Path(root) / "tools"


def build_command(root=KIT_ROOT, target_dir=None):
    command = ["cargo", "build", "--release", "--locked", "--manifest-path", str(Path(root) / "Cargo.toml")]
    return command + (["--target-dir", str(target_dir)] if target_dir else [])


def tool_path(name, explicit=None, environ=None, root=KIT_ROOT):
    """The program for a tool: the explicit path, its environment variable, the ready-built folder, the build folder, then
    the repository's own target folder. When none exists, the build folder's path (where a build would put it)."""
    environ = os.environ if environ is None else environ
    if explicit:
        return Path(explicit)
    if environ.get(ENV_VARS.get(name, "")):
        return Path(environ[ENV_VARS[name]])
    candidates = [bundled_dir(environ, root) / program_name(name),
                  build_dir(environ) / "release" / program_name(name),
                  Path(root) / "target" / "release" / program_name(name)]
    return next((c for c in candidates if c.is_file()), candidates[1])


def require_tool(name, explicit=None, environ=None, root=KIT_ROOT):
    path = tool_path(name, explicit, environ, root)
    if not path.is_file():
        command = " ".join(f'"{part}"' if " " in part else part for part in build_command(root, build_dir(environ)))
        raise ToolMissing(f"The {name} program is not built yet. Run this command again with --build-indexer, or "
                          f"build it once with Rust installed:\n  {command}")
    return path


def build_tools(root=KIT_ROOT, environ=None, run=subprocess.run):
    """Build every Rust tool into the build folder. Raises ToolMissing when cargo is missing or the build fails."""
    if run is subprocess.run and shutil.which("cargo") is None:
        raise ToolMissing("cargo is not installed; install Rust from https://rustup.rs to build the kit's tools.")
    result = run(build_command(root, build_dir(environ)), cwd=str(root))
    if result.returncode != 0:
        raise ToolMissing(f"cargo build failed (exit code {result.returncode}); see its messages above.")
