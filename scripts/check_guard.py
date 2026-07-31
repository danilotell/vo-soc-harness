#!/usr/bin/env python3
"""
Assert that the harness guardrails are actually in force before operating.

``.opencode/plugins/harness-guard.js`` is what keeps the agent out of ``.env`` and
out of ``mcp_server/`` however a path was spelled, and what validates a state write
before it lands. A guard that fails to load drops every one of those rules while
the rest of the harness keeps working. A plugin in the wrong directory fails that
way, and so does one OpenCode refuses to import — a single non-function export is
enough, and the only symptom is this script.

The human-approval gate for containment is NOT what this verifies: that is the
``permission`` map in ``opencode.json``, which OpenCode applies itself.

Two independent things have to hold, and neither implies the other:

* **The code is correct** — ``probe_harness_guard.mjs`` drives the real hook and
  asserts every decision. It passes even if OpenCode never loaded the plugin.
* **The code is loaded** — the guard writes ``.opencode/guard-status.json`` when
  it loads and refreshes it on every tool call. It stays fresh even if the hook
  logic is wrong.

The result is an exit code, not prose: the preflight reports what this returns
instead of judging the guard itself.

Usage (through ``uv``, standard library only):
    uv run --no-project scripts/check_guard.py              # both assertions
    uv run --no-project scripts/check_guard.py --probe-only # correctness only (CI)

Exit code 0 = the guardrails are in force, 1 = they are not.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "scripts" / "probe_harness_guard.mjs"
STATUS_FILE = ROOT / ".opencode" / "guard-status.json"
PLUGIN = ROOT / ".opencode" / "plugins" / "harness-guard.js"
# The guard belongs in `plugins/` (plural). A copy left in the singular directory
# is an invisible cause of a guard that never loads.
LEGACY_PLUGIN_DIR = ROOT / ".opencode" / "plugin"

# The marker is refreshed on every tool call, and the preflight reaches this
# script through one, so anything older than this means the hook is not running.
MAX_AGE_SECONDS = 120

# Bumped in harness-guard.js when the hook contract changes.
EXPECTED_VERSION = 1


def check_probe() -> list[str]:
    """Run the hook probe. Failure to run it counts as failure, never as a pass."""
    if not PLUGIN.exists():
        return [
            f"{PLUGIN.relative_to(ROOT).as_posix()} does not exist: there is no guard to load."
        ]
    if not PROBE.exists():
        return [
            f"{PROBE.relative_to(ROOT).as_posix()} is missing: the guard cannot be verified."
        ]
    node = shutil.which("node")
    if node is None:
        return ["node is not on PATH, so the guard's behaviour cannot be verified."]

    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [node, str(PROBE)], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode == 0:
        return []
    output = (result.stdout + result.stderr).strip()
    failed = [line for line in output.splitlines() if line.startswith("FAIL")]
    return [
        "The guard does not behave as declared:",
        *(f"    {line}" for line in failed or [output]),
    ]


def load_hint() -> str:
    """Say why the guard may not be loaded, based on what is actually on disk.

    A fixed hint is worse than none: telling the operator to move a file that is
    already in the right place sends them to fix something that is not broken.
    """
    stray = sorted(LEGACY_PLUGIN_DIR.glob("*.js")) if LEGACY_PLUGIN_DIR.is_dir() else []
    if stray:
        return (
            "There is a copy under .opencode/plugin/ "
            f"({', '.join(p.name for p in stray)}): the guard belongs in "
            ".opencode/plugins/ (plural) and only there. Remove the stray copy."
        )
    if not PLUGIN.exists():
        return f"{PLUGIN.relative_to(ROOT).as_posix()} is missing: there is no guard to load."
    return (
        f"{PLUGIN.relative_to(ROOT).as_posix()} is where OpenCode looks, so it was found and "
        "not loaded. `opencode debug info` lists the plugins it loaded; a refusal is logged as "
        "`failed to load plugin` (`opencode debug paths` shows the log). Note OpenCode imports "
        "the plugin only at startup: restart it after editing this file."
    )


def check_heartbeat() -> list[str]:
    """Read the liveness marker the guard writes from its hooks."""
    hint = load_hint()
    if not STATUS_FILE.exists():
        return [
            f"{STATUS_FILE.relative_to(ROOT).as_posix()} does not exist: "
            "OpenCode has not loaded the guard in this session.",
            f"    {hint}",
        ]

    try:
        marker = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{STATUS_FILE.relative_to(ROOT).as_posix()} is unreadable: {exc}"]

    problems = []
    if marker.get("active") is not True:
        problems.append("The guard reports itself as inactive.")
    if marker.get("version") != EXPECTED_VERSION:
        problems.append(
            f"Marker version {marker.get('version')!r}, expected {EXPECTED_VERSION}: "
            "the running guard does not match this checkout."
        )

    seen_at = marker.get("seen_at")
    if not isinstance(seen_at, (int, float)):
        problems.append("The marker carries no usable timestamp.")
    else:
        age = time.time() - seen_at / 1000
        if age > MAX_AGE_SECONDS:
            problems.append(
                f"The marker was last refreshed {int(age)}s ago (limit {MAX_AGE_SECONDS}s): "
                "the hooks are not running in this session."
            )
            problems.append(f"    {hint}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="check the guard's behaviour but not its liveness (for CI, which has no session)",
    )
    args = parser.parse_args()

    problems = check_probe()
    if not args.probe_only:
        problems += check_heartbeat()

    if problems:
        print("The harness guardrails are NOT verified.", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nWithout them a state write lands unvalidated and the path rules that "
            "protect .env and mcp_server/ are gone. The approval gate for containment "
            "is the permission map in opencode.json and does not depend on this.",
            file=sys.stderr,
        )
        return 1

    scope = "behaviour" if args.probe_only else "behaviour and liveness"
    print(f"Harness guardrails verified ({scope}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
