"""The kit's assembly reader (dotnet/PhobosModKit.Assemblies): built into the kit's build folder on first use, and again when the
kit's version changes. It reads .NET assemblies through their metadata and method bodies, never loading or running them: Harmony
patches (patches), a type's members (members), and which methods call which (calls). Game-free: a game's adapter chooses the files.
How it is built and found is `dotnet_tools`, shared with the heap reader.
"""
from __future__ import annotations

import shutil
import subprocess

from .dotnet_tools import DotnetTool, ToolBuildError

READER_NAME = "PhobosModKit.Assemblies"
BUNDLED_FOLDER = "assemblies"   # inside native.bundled_dir: the reader as an installer brought it (programs bundle, 1.62.0)


class ReaderError(ToolBuildError):
    """The reader could not be built."""


TOOL = DotnetTool(READER_NAME, BUNDLED_FOLDER, "read assemblies", ReaderError)
READER_PROJECT = TOOL.project_file


def reader_folder(environ=None):
    return TOOL.build_folder(environ)


def reader_path(environ=None):
    return TOOL.built_path(environ)


def bundled_reader(environ=None):
    """The reader an installer brought ready-built, or None. It needs only the .NET runtime, and is the kit's own version."""
    return TOOL.bundled_path(environ)


def publish_reader(folder, environ=None, run=subprocess.run, which=shutil.which):
    """Builds the reader for an installer to carry: published into `folder`, needing only the .NET runtime where it runs."""
    TOOL.publish(folder, environ, run, which)


def build_reader(environ=None, run=subprocess.run):
    """Build the C# reader into the kit's build folder. Raises ReaderError without the .NET SDK or on failure."""
    TOOL.build(environ, run)


def ensure_reader(environ=None, run=subprocess.run):
    """The reader's path: the one an installer brought, else the kit's build, built first when it is missing or was built by
    another version of the kit."""
    return TOOL.ensure(environ, run)
