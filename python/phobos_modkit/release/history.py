"""A read-only screen of every file a Git repository's history can reach, before the repository is made public.

Names each finding by category, path and object ID, never by its contents. A bounded pattern screen, not a
guarantee that no secret is present and not a licence audit. Submodules are separate repositories: screen each.
Fetch remote branches first so their history is included.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path, PurePosixPath
import re
import subprocess

PATTERNS = {
    "credential-pattern": re.compile(
        rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-proj-[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}"
        rb"|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"),
    "personal-machine-path": re.compile(
        rb"[C-Z]:[\\/](?:Users|SynologyDrive)[\\/][^\s\x00<>\"\r\n]+|/(?:home|Users)/[a-z][a-z0-9._-]+/[^\s\x00<>\"\r\n]+"),
}
REFUSED_SUFFIXES = frozenset({".dll", ".exe", ".zip", ".sav", ".rws", ".dmp", ".pfx", ".p12", ".pem", ".key"})
BINARY_PROBE = 8192


def screen(repository):
    """(findings, blobs): sorted (category, path, short object ID) tuples, and how many file objects were read."""
    repository = Path(repository)
    rows = subprocess.check_output(["git", "rev-list", "--objects", "--all"], cwd=repository).decode("utf-8").splitlines()
    counts, findings = Counter(), set()
    with subprocess.Popen(["git", "cat-file", "--batch"], cwd=repository, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE) as process:
        for row in rows:
            oid, _, path = row.partition(" ")
            process.stdin.write((oid + "\n").encode("ascii"))
            process.stdin.flush()
            header = process.stdout.readline().decode("ascii").split()
            if len(header) != 3:
                raise RuntimeError("Unexpected answer from git cat-file")
            data = process.stdout.read(int(header[2]))
            process.stdout.read(1)
            if header[1] != "blob":
                continue
            counts["blobs"] += 1
            if PurePosixPath(path).suffix.lower() in REFUSED_SUFFIXES:
                findings.add(("refused-file-type", path, oid[:12]))
            if b"\0" in data[:BINARY_PROBE]:
                continue
            for category, pattern in PATTERNS.items():
                if pattern.search(data):
                    findings.add((category, path, oid[:12]))
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("git cat-file failed")
    return sorted(findings), counts["blobs"]
