"""Load a gate's steps, run them in stages and lanes, and build the report.

config/gate.json:

    {
      "schemaVersion": 1,
      "stages": [
        {"name": "Build and check", "steps": [
          {"name": "build {stem}", "each": "src/*/*.csproj", "lane": "dotnet", "parser": "msbuild",
           "run": ["dotnet", "build", "{path}", "--nologo", "-v", "q"], "requires": "dotnet"},
          {"name": "python tests", "parser": "unittest", "run": ["{python}", "-m", "unittest", "discover", "-s", "tests"]}
        ]},
        {"name": "Tests", "steps": [ ... ]}
      ]
    }

Placeholders in a step's name, run, cwd and env: {python} (this interpreter), {root}, {cargo_target} (where the kit's
Rust tools build), {env:NAME}; and for an "each" step {path} (relative, forward slashes), {name}, {stem} and {dir}.
A step whose "requires" program is not on the PATH is skipped and says so. A failed stage stops the stages after it,
unless the caller keeps going.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .. import native
from .parsers import PARSERS, Parsed

CONFIG = "config/gate.json"
DEFAULT_TIMEOUT = 1800
PLACEHOLDER = re.compile(r"\{(env:[A-Za-z_][A-Za-z0-9_]*|[a-z_]+)\}")


class GateError(ValueError):
    pass


@dataclass
class Step:
    name: str
    run: list
    stage: str
    lane: str
    parser: str = "text"
    cwd: str = ""
    env: dict = field(default_factory=dict)
    requires: str = ""
    timeout: int = DEFAULT_TIMEOUT


@dataclass
class Result:
    step: Step
    state: str                        # passed, failed, skipped
    seconds: float = 0.0
    parsed: Parsed = field(default_factory=Parsed)
    reason: str = ""                  # why a step was skipped
    log: str = ""                     # where a failed step's full output was kept


def substitute(value, values, environ):
    def one(match):
        key = match[1]
        if key.startswith("env:"):
            return environ.get(key[4:], "")
        if key not in values:
            raise GateError(f"Unknown placeholder {{{key}}} in {value!r}")
        return values[key]
    return PLACEHOLDER.sub(one, value)


def load(root, config=CONFIG, environ=None):
    """The gate's steps, with every "each" expanded over the files its globs find, in a stable order."""
    root, environ = Path(root), (os.environ if environ is None else environ)
    path = root / config
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GateError(f"No gate at {config}; write one (docs/gate.md in phobos-modkit)") from None
    except ValueError as error:
        raise GateError(f"{config} is not valid JSON: {error}") from None
    if data.get("schemaVersion") != 1:
        raise GateError(f"{config}: schemaVersion must be 1")
    base = {"python": sys.executable, "root": str(root), "cargo_target": str(native.build_dir(environ))}
    stages = []
    for stage_index, stage in enumerate(data.get("stages", [])):
        stage_name = stage.get("name") or f"stage {stage_index + 1}"
        steps = []
        for spec in stage.get("steps", []):
            if not spec.get("name") or not isinstance(spec.get("run"), list) or not spec["run"]:
                raise GateError(f"{config}: every step needs a name and a run list ({spec!r})")
            if spec.get("parser", "text") not in PARSERS:
                raise GateError(f"{config}: unknown parser {spec['parser']!r}; one of {', '.join(sorted(PARSERS))}")
            patterns = spec.get("each")
            patterns = [patterns] if isinstance(patterns, str) else patterns
            matches = [None]
            if patterns:
                found = {p.relative_to(root).as_posix() for pattern in patterns for p in root.glob(pattern) if p.is_file()}
                matches = sorted(found)
            for match in matches:
                values = dict(base)
                if match is not None:
                    p = Path(match)
                    values.update(path=match, name=p.name, stem=p.stem, dir=p.parent.as_posix())
                name = substitute(spec["name"], values, environ)
                steps.append(Step(
                    name=name, stage=stage_name,
                    run=[substitute(part, values, environ) for part in spec["run"]],
                    lane=substitute(spec.get("lane", name), values, environ),
                    parser=spec.get("parser", "text"),
                    cwd=substitute(spec.get("cwd", ""), values, environ),
                    env={k: substitute(v, values, environ) for k, v in spec.get("env", {}).items()},
                    requires=spec.get("requires", ""),
                    timeout=int(spec.get("timeout", DEFAULT_TIMEOUT))))
        stages.append((stage_name, steps))
    return stages


def select(stages, only=(), skip=()):
    """Keep the steps whose name matches any --only pattern (all when none) and no --skip pattern."""
    def wanted(step):
        if only and not any(fnmatch.fnmatchcase(step.name, p) for p in only):
            return False
        return not any(fnmatch.fnmatchcase(step.name, p) for p in skip)
    return [(name, [s for s in steps if wanted(s)]) for name, steps in stages]


def _log_name(step):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", step.name).strip("-")[:80] + ".txt"


def run_step(step, root, environ, logs=None, which=shutil.which, runner=subprocess.run, clock=time.monotonic):
    if step.requires and not which(step.requires):
        return Result(step, "skipped", reason=f"{step.requires} is not on the PATH")
    env = dict(environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("DOTNET_CLI_UI_LANGUAGE", "en")
    env.setdefault("DOTNET_NOLOGO", "1")
    env.update(step.env)
    cwd = Path(root) / step.cwd if step.cwd else Path(root)
    started = clock()
    try:
        done = runner(step.run, cwd=cwd, env=env, capture_output=True, timeout=step.timeout, check=False)
        output = (done.stdout or b"").decode("utf-8", "replace") + (done.stderr or b"").decode("utf-8", "replace")
        ok = done.returncode == 0
    except FileNotFoundError:
        return Result(step, "failed", parsed=Parsed(summary="could not start", problems=[f"{step.run[0]} was not found"]))
    except subprocess.TimeoutExpired as expired:
        output = (expired.stdout or b"").decode("utf-8", "replace") if isinstance(expired.stdout, bytes) else ""
        ok = False
        output += f"\n(stopped after {step.timeout} s)"
    seconds = clock() - started
    parsed = PARSERS[step.parser](output, ok, root)
    if not ok and not parsed.problems:
        parsed.problems = ["exited with an error and printed nothing the gate recognises"]
    result = Result(step, "passed" if ok else "failed", seconds, parsed)
    if not ok and logs is not None:
        logs.mkdir(parents=True, exist_ok=True)
        target = logs / _log_name(step)
        target.write_text(output, encoding="utf-8")
        result.log = str(target)
    return result


def run(stages, root, environ=None, jobs=4, keep_going=False, logs=None, **step_options):
    """Every stage in order; inside one, each lane's steps in order and the lanes side by side. Returns all results."""
    environ = os.environ if environ is None else environ
    results, stopped = [], False
    for _, steps in stages:
        if stopped:
            results += [Result(s, "skipped", reason="an earlier stage failed") for s in steps]
            continue
        lanes = {}
        for step in steps:
            lanes.setdefault(step.lane, []).append(step)

        def run_lane(lane_steps):
            return [run_step(s, root, environ, logs, **step_options) for s in lane_steps]

        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            done = list(pool.map(run_lane, lanes.values()))
        order = {id(s): i for i, s in enumerate(steps)}
        stage_results = sorted((r for lane in done for r in lane), key=lambda r: order[id(r.step)])
        results += stage_results
        if any(r.state == "failed" for r in stage_results) and not keep_going:
            stopped = True
    return results
