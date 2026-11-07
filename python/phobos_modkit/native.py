"""The kit's compiled tools: where to find them and how to build them.

The Rust tools build from this repository with `cargo build --release --locked`; their programs land in
target/release and are never committed.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

KIT_ROOT = Path(__file__).resolve().parents[2]
ENV_VARS = {"xml-index": "PHOBOS_XML_INDEX"}  # name -> environment variable that points at the program


class ToolMissing(RuntimeError):
    pass


def program_name(name, platform=None):
    return f"{name}.exe" if (platform or sys.platform) == "win32" else name


def build_command(root=KIT_ROOT):
    return ["cargo", "build", "--release", "--locked", "--manifest-path", str(Path(root) / "Cargo.toml")]


def tool_path(name, explicit=None, environ=None, root=KIT_ROOT):
    """The program for a tool: the explicit path, then its environment variable, then this kit's release build."""
    environ = os.environ if environ is None else environ
    if explicit:
        return Path(explicit)
    if environ.get(ENV_VARS.get(name, "")):
        return Path(environ[ENV_VARS[name]])
    return Path(root) / "target" / "release" / program_name(name)


def require_tool(name, explicit=None, environ=None, root=KIT_ROOT):
    path = tool_path(name, explicit, environ, root)
    if not path.is_file():
        command = " ".join(f'"{part}"' if " " in part else part for part in build_command(root))
        raise ToolMissing(f"The {name} program is not built yet ({path}). Build it once with Rust installed:\n"
                          f"  {command}\nor run this command again with --build-indexer.")
    return path


def build_tools(root=KIT_ROOT, run=subprocess.run):
    """Build every Rust tool. Raises ToolMissing when cargo is not installed or the build fails."""
    if run is subprocess.run and shutil.which("cargo") is None:
        raise ToolMissing("cargo is not installed; install Rust from https://rustup.rs to build the kit's tools.")
    result = run(build_command(root), cwd=str(root))
    if result.returncode != 0:
        raise ToolMissing(f"cargo build failed (exit code {result.returncode}); see its messages above.")
