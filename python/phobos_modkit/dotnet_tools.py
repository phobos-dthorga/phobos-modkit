"""The kit's C# tools (`dotnet/`): built into the kit's build folder on first use and again when the kit's version changes, or found
ready-built where an installer brought them (`programs bundle`). Game-free.

Each tool is one `DotnetTool`: the assembly reader (`assemblies`) and the heap reader (`heap_reader`) are two of them.
"""
from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess

from . import __version__
from . import native

STAMP = "kit-version.txt"
SDK_MISSING = "The .NET SDK is not installed; install .NET 10 from https://dotnet.microsoft.com to {purpose}."


class ToolBuildError(RuntimeError):
    """A C# tool could not be built."""


@dataclass(frozen=True)
class DotnetTool:
    project: str        # the project's folder under dotnet/, which is also its program's name
    folder: str         # its folder in the build folder (dotnet/tool/<folder>) and in a bundle
    purpose: str        # what it is for, ending the sentence "install .NET 10 to ..."
    error: type = ToolBuildError

    @property
    def project_file(self):
        return native.KIT_ROOT / "dotnet" / self.project / f"{self.project}.csproj"

    def build_folder(self, environ=None):
        return native.build_dir(environ) / "dotnet" / "tool" / self.folder

    def built_path(self, environ=None):
        return self.build_folder(environ) / native.program_name(self.project)

    def bundled_path(self, environ=None):
        """The tool an installer brought ready-built, or None. It needs only the .NET runtime, and is the kit's own version."""
        path = native.bundled_dir(environ) / self.folder / native.program_name(self.project)
        return path if path.is_file() else None

    def _sdk(self, run, which):
        if run is subprocess.run and which("dotnet") is None:
            raise self.error(SDK_MISSING.format(purpose=self.purpose))

    def publish(self, folder, environ=None, run=subprocess.run, which=shutil.which):
        """Builds the tool for an installer to carry: published into `folder`, needing only the .NET runtime where it runs."""
        self._sdk(run, which)
        command = ["dotnet", "publish", str(self.project_file), "-c", "Release", "-o", str(folder), "--nologo", "-v", "q",
                   "-p:DebugType=none"]
        result = run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise self.error(f"Publishing {self.project} failed:\n{(result.stdout or '')[-2000:]}")

    def build(self, environ=None, run=subprocess.run, which=shutil.which):
        """Build the tool into the kit's build folder."""
        self._sdk(run, which)
        command = ["dotnet", "build", str(self.project_file), "-c", "Release", "-o", str(self.build_folder(environ)), "--nologo",
                   "-v", "q"]
        result = run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise self.error(f"Building {self.project} failed:\n{(result.stdout or '')[-2000:]}")

    def ensure(self, environ=None, run=subprocess.run):
        """The tool's path: the one an installer brought, else the kit's build, built first when it is missing or was built by
        another version of the kit."""
        bundled = self.bundled_path(environ)
        if bundled is not None:
            return bundled
        tool = self.built_path(environ)
        stamp = self.build_folder(environ) / STAMP
        current = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""
        if not tool.is_file() or current != __version__:
            self.build(environ, run)
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(__version__, encoding="utf-8")
        return tool
