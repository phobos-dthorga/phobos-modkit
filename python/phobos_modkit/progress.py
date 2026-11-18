"""Progress while a command works: one JSON line a step on standard error, only when a program asks for it.

A program that wants progress sets the environment variable PHOBOS_MODKIT_PROGRESS to 1 and reads the command's standard error
line by line while it runs. Each progress line is one JSON object:

    {"progress": 1, "label": "Building PhobosFramework", "step": 3, "of": 23}
    {"progress": 1, "label": "Reading the save"}
    {"progress": 1, "detail": "  copied 412 files"}

- label: what is being done now, in words a person can read. A line without one keeps the last label.
- step and of: how far along, when the command can count its work (step from 1). Without them the work cannot be counted.
- detail: a line of the work's own output, as a second, quieter status under the label.

Standard output is untouched: the envelope or the Markdown still arrives whole at the end. Without the variable nothing is written,
so a person at a console and every test see no change. A repository's own command (an install, a build) can speak the same lines:
the kit passes its progress lines on, and turns its ordinary output lines into details.
"""
from __future__ import annotations

import json
import os
import sys
import threading

ENV = "PHOBOS_MODKIT_PROGRESS"
FORMAT = 1
_LOCK = threading.Lock()


def wanted(environ=None):
    environ = os.environ if environ is None else environ
    return environ.get(ENV, "") not in ("", "0")


def line(label=None, step=None, of=None, detail=None):
    """One progress line as text, without its newline."""
    message = {"progress": FORMAT}
    if label:
        message["label"] = str(label)
    if step is not None and of:
        message["step"], message["of"] = int(step), int(of)
    if detail:
        message["detail"] = str(detail)
    return json.dumps(message, ensure_ascii=False)


def is_line(text):
    """Whether a line of a command's standard error is a progress line."""
    return text.lstrip().startswith('{"progress":')


class Progress:
    """Writes progress lines to a stream when asked to; says nothing otherwise. Safe to call from several threads."""

    def __init__(self, environ=None, stream=None):
        self.on = wanted(environ)
        self.stream = stream

    def __call__(self, label=None, step=None, of=None, detail=None):
        if self.on:
            self.write(line(label, step, of, detail))

    def write(self, text):
        """Writes one ready-made progress line (a child command's, passed on)."""
        if not self.on:
            return
        stream = self.stream or sys.stderr
        with _LOCK:
            try:
                stream.write(text.rstrip("\r\n") + "\n")
                stream.flush()
            except (OSError, ValueError):
                self.on = False     # the reader went away; the work itself carries on


def silent():
    """A Progress that never writes, for callers that take one."""
    return Progress(environ={})


def run_streaming(command, cwd=None, env=None, timeout=None, progress=None, popen=None):
    """Runs a command to its end, passing its progress lines on and turning its ordinary output lines into details as they come.

    Returns (exit code, lines): every output line, standard output's first, then standard error's ordinary lines. Raises
    subprocess.TimeoutExpired after stopping the command when it runs past timeout seconds, and OSError when it cannot start."""
    import subprocess

    progress = progress or silent()
    child_env = dict(os.environ if env is None else env)
    if progress.on:
        child_env[ENV] = "1"
    else:
        child_env.pop(ENV, None)
    child = (popen or subprocess.Popen)(command, cwd=cwd, env=child_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    out_lines, err_lines = [], []

    def read_out():
        for raw in child.stdout:
            text = raw.rstrip("\r\n")
            out_lines.append(text)
            if text.strip():
                progress(detail=text.strip())

    def read_err():
        for raw in child.stderr:
            text = raw.rstrip("\r\n")
            if is_line(text):
                progress.write(text)
            else:
                err_lines.append(text)

    readers = [threading.Thread(target=read_out, daemon=True), threading.Thread(target=read_err, daemon=True)]
    for reader in readers:
        reader.start()
    try:
        code = child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        raise
    finally:
        for reader in readers:
            reader.join(timeout=5)
        for pipe in (child.stdout, child.stderr):
            if pipe is not None:
                pipe.close()
    return code, out_lines + err_lines
