"""The kit's C# tools (`dotnet/`): built into the kit's build folder on first use and again when the kit's version changes, or found
ready-built where an installer brought them (`programs bundle`). Game-free.

Each tool is one `DotnetTool`: the assembly reader (`assemblies`) and the heap reader (`heap_reader`) are two of them.
"""
from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess

from . import __version__
from . import file_lock
from . import native

STAMP = "kit-version.txt"
# A first build restores packages and can take a few minutes; a lock older than half an hour was left by a run that stopped.
BUILD_WAIT_S = 10 * 60
BUILD_STALE_S = 30 * 60
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
        """Its build, one folder per version of the kit (1.79.1): repositories pin different versions, and with one shared
        folder each rebuilt the tool over the other's whenever their versions differed, so a run could find it half written or
        built from other source (seen 23 Nov 2026: phobos-rimworld's pinned 1.75.0 and the kit's own tests)."""
        return native.build_dir(environ) / "dotnet" / "tool" / self.folder / __version__

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

    def _current(self, environ):
        stamp = self.build_folder(environ) / STAMP
        built = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""
        return self.built_path(environ).is_file() and built == __version__

    def ensure(self, environ=None, run=subprocess.run):
        """The tool's path: the one an installer brought, else the kit's build, built first when it is missing or was built by
        another version of the kit. One run builds at a time (1.70.2): two runs starting together after an update, such as the
        gate's two Python lanes, both found the tool out of date and wrote the same files at once; the one that waited now finds
        it built."""
        bundled = self.bundled_path(environ)
        if bundled is not None:
            return bundled
        tool = self.built_path(environ)
        if self._current(environ):
            return tool
        folder = self.build_folder(environ)
        try:
            with file_lock.held(folder.with_name(folder.name + ".lock"), BUILD_WAIT_S, BUILD_STALE_S):
                if not self._current(environ):
                    self.build(environ, run)
                    (folder / STAMP).parent.mkdir(parents=True, exist_ok=True)
                    (folder / STAMP).write_text(__version__, encoding="utf-8")
        except file_lock.LockBusy:
            raise self.error(f"Another run has been building {self.project} for over {BUILD_WAIT_S // 60} minutes; "
                             "try again when it ends.") from None
        return tool
