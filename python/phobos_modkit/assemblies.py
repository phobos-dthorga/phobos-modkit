"""The kit's assembly reader (dotnet/PhobosModKit.Assemblies): built into the kit's build folder on first use, and again when the
kit's version changes. It reads .NET assemblies through their metadata and method bodies, never loading or running them: Harmony
patches (patches), a type's members (members), and which methods call which (calls). Game-free: a game's adapter chooses the files.
"""
from __future__ import annotations

import shutil
import subprocess

from . import __version__
from . import native

READER_PROJECT = native.KIT_ROOT / "dotnet" / "PhobosModKit.Assemblies" / "PhobosModKit.Assemblies.csproj"
READER_NAME = "PhobosModKit.Assemblies"
BUNDLED_FOLDER = "assemblies"   # inside native.bundled_dir: the reader as an installer brought it (programs bundle, 1.62.0)


class ReaderError(RuntimeError):
    """The reader could not be built."""


def reader_folder(environ=None):
    return native.build_dir(environ) / "dotnet" / "tool" / "assemblies"


def reader_path(environ=None):
    return reader_folder(environ) / native.program_name(READER_NAME)


def bundled_reader(environ=None):
    """The reader an installer brought ready-built, or None. It needs only the .NET runtime, and is the kit's own version."""
    path = native.bundled_dir(environ) / BUNDLED_FOLDER / native.program_name(READER_NAME)
    return path if path.is_file() else None


def publish_reader(folder, environ=None, run=subprocess.run, which=shutil.which):
    """Builds the reader for an installer to carry: published into `folder`, needing only the .NET runtime where it runs."""
    if run is subprocess.run and which("dotnet") is None:
        raise ReaderError("The .NET SDK is not installed; install .NET 10 from https://dotnet.microsoft.com to build the reader.")
    command = ["dotnet", "publish", str(READER_PROJECT), "-c", "Release", "-o", str(folder), "--nologo", "-v", "q",
               "-p:DebugType=none"]
    result = run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ReaderError(f"Publishing the assembly reader failed:\n{(result.stdout or '')[-2000:]}")


def build_reader(environ=None, run=subprocess.run):
    """Build the C# reader into the kit's build folder. Raises ReaderError without the .NET SDK or on failure."""
    if run is subprocess.run and shutil.which("dotnet") is None:
        raise ReaderError("The .NET SDK is not installed; install .NET 10 from https://dotnet.microsoft.com to read assemblies.")
    command = ["dotnet", "build", str(READER_PROJECT), "-c", "Release", "-o", str(reader_folder(environ)), "--nologo",
               "-v", "q"]
    result = run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ReaderError(f"Building the assembly reader failed:\n{(result.stdout or '')[-2000:]}")


def ensure_reader(environ=None, run=subprocess.run):
    """The reader's path: the one an installer brought, else the kit's build, built first when it is missing or was built by
    another version of the kit."""
    bundled = bundled_reader(environ)
    if bundled is not None:
        return bundled
    tool = reader_path(environ)
    stamp = reader_folder(environ) / "kit-version.txt"
    current = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""
    if not tool.is_file() or current != __version__:
        build_reader(environ, run)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(__version__, encoding="utf-8")
    return tool


