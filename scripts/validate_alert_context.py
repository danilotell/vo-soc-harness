#!/usr/bin/env python3
"""
Validate the harness' JSON state against the reference templates.

The subagents hand each other JSON and that contract only lives in a prompt, so
this script makes it executable: a malformed handoff is caught at the moment it
happens and named by the exact key that is wrong.

The templates state the **minimum**, not the maximum:

* Every key a template declares must exist, so a rename or a typo shows up as an
  absence.
* Keys a template does not declare are accepted and listed as notes, so drift
  stays visible without being fatal.
* A whole new top-level section is refused: that is a field which belongs inside
  an existing section.
* For lists, the first template element describes every item. Scalar values are
  examples and are not type-checked; ``null`` means "must exist, shape is free".

Usage (through ``uv``, so it does not depend on a ``python`` being on PATH;
``--no-project`` because this is standard-library only and must not pull in
``mcp_server/``'s project):
    uv run --no-project scripts/validate_alert_context.py             # validate the repo state
    uv run --no-project scripts/validate_alert_context.py --self-test # check the checker itself

Exit code 0 = valid (or nothing to validate), 1 = problems found.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REFERENCES = ROOT / "docs" / "references"

# Section of alert_context.json -> template file that defines its shape.
SECTION_TEMPLATES = {
    "triage": "template_triage.json",
    "analysis": "template_analysis.json",
    "responses": "template_responses.json",
}

# Runtime state file -> the seed that declares its canonical empty shape. The
# state files are NOT versioned (they hold live tenant data); the seeds are.
STATE_FILES = {
    "alert_context": (
        Path("context") / "alert_context.json",
        "seed_alert_context.json",
    ),
    "workbench": (Path("workbench_list.json"), "seed_workbench_list.json"),
    "history": (Path("memory") / "history.json", "seed_history.json"),
}

# Fields SOC.md renders in the workbench table; missing ones break the listing.
WORKBENCH_ALERT_FIELDS = (
    "id",
    "model",
    "description",
    "status",
    "score",
    "severity",
    "createdDateTime",
    "workbenchLink",
)


def compare(data: Any, template: Any, path: str) -> list[str]:
    """Every declared field that is missing or has the wrong container type."""
    problems: list[str] = []

    if isinstance(template, dict):
        if not isinstance(data, dict):
            return [f"{path}: expected an object, got {type(data).__name__}"]
        for key in sorted(set(template) - set(data)):
            problems.append(f"{path}.{key}: missing (required by the template)")
        for key in sorted(set(template) & set(data)):
            problems += compare(data[key], template[key], f"{path}.{key}")
        return problems

    if isinstance(template, list):
        if not isinstance(data, list):
            return [f"{path}: expected an array, got {type(data).__name__}"]
        if template and isinstance(template[0], dict):
            for index, item in enumerate(data):
                problems += compare(item, template[0], f"{path}[{index}]")
        return problems

    # Scalars in a template are placeholder examples ("...", "N/A"), not types.
    # `null` is the deliberate escape hatch: the field must exist, its shape is
    # free. Used for the free-form evidence blobs of a history digest, which the
    # agents legitimately structure differently per alert.
    return problems


def extra_keys(data: Any, template: Any, path: str) -> list[str]:
    """Keys present in the data that the template does not declare; never fatal."""
    notes: list[str] = []
    if isinstance(template, dict) and isinstance(data, dict):
        notes += [f"{path}.{key}" for key in sorted(set(data) - set(template))]
        for key in sorted(set(template) & set(data)):
            notes += extra_keys(data[key], template[key], f"{path}.{key}")
    elif isinstance(template, list) and isinstance(data, list):
        if template and isinstance(template[0], dict):
            for index, item in enumerate(data):
                notes += extra_keys(item, template[0], f"{path}[{index}]")
    return notes


# Values an agent may legitimately write when it could not obtain data. A declared
# gap is information; a filled-in gap is a false datum, so these are always valid.
UNKNOWN_MARKERS = frozenset({"N/A", "NOT_COLLECTED", "UNAVAILABLE"})

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_ALERT_ID = re.compile(r"^(?:WB|IC)-[A-Za-z0-9-]+$")
_GUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def _walk_strings(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Yield ``(path, value)`` for every string anywhere in a JSON document."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _walk_strings(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_strings(value, f"{path}[{index}]")


def _is_placeholder(value: str) -> bool:
    """Whether a template string is example data rather than a real enum value.

    ``"high"`` or ``"done"`` are values an agent is meant to reuse; an alert ID, a
    timestamp or an address is example data that must never survive into a live
    document.

    Note which GUIDs count: a zeroed one is a placeholder, but the detection-rule
    GUIDs in the sample payload are global Vision One identifiers that a real alert
    legitimately carries, so matching every GUID would reject valid triages.
    """
    text = value.strip()
    if text == "...":
        return True
    if "@" in text or "example" in text.lower() or "THE_WORKBENCH_URL" in text:
        return True
    if _GUID.match(text) and set(text) <= {"0", "-"}:
        return True
    return bool(_ISO_DATE.match(text) or _ALERT_ID.match(text) or _IPV4.match(text))


def _load(path: Path) -> Any:
    try:
        # utf-8-sig: same reason as run_check — an editor that writes a BOM must not
        # look like a malformed template.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise SystemExit(f"Missing file: {path.relative_to(ROOT)}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path.relative_to(ROOT)} is not valid JSON: {exc}") from None


def _templates() -> dict[str, Any]:
    """Load each section template, unwrapping its single top-level key."""
    templates = {}
    for section, filename in SECTION_TEMPLATES.items():
        content = _load(REFERENCES / filename)
        templates[section] = content.get(section, content)
    return templates


def placeholder_values() -> set[str]:
    """Example values used by the reference documents, derived from the files.

    Derived rather than hardcoded so editing a template keeps the check honest.
    """
    values: set[str] = set()
    for path in sorted(REFERENCES.glob("*.json")):
        for _, value in _walk_strings(_load(path)):
            if _is_placeholder(value):
                values.add(value.strip())
    return values


def validate_alert_context(data: Any, templates: dict[str, Any]) -> list[str]:
    """Validate one alert context. An empty object means 'idle', which is valid."""
    if data == {}:
        return []
    if not isinstance(data, dict):
        return [f"alert_context: expected an object, got {type(data).__name__}"]

    problems = []
    for section in data:
        if section not in templates:
            problems.append(f"alert_context.{section}: unknown section")
    # A context is built up step by step, so a section that is not there yet is
    # fine; one that IS there must match its template exactly.
    for section, template in templates.items():
        if section in data:
            problems += compare(data[section], template, f"alert_context.{section}")
    problems += check_response_targets(data)
    problems += check_executed_are_authorized(data)
    return problems


def check_copied_placeholders(data: Any, placeholders: set[str]) -> list[str]:
    """Flag example values from the templates that leaked into live data.

    Copying the template's sample alert ID, host or timestamp is the most common
    shape of fabrication: the model reproduces the format it was shown instead of
    reporting what it actually read.
    """
    problems = []
    for path, value in _walk_strings(data):
        text = value.strip()
        if text == "...":
            problems.append(f"{path}: still the template placeholder '...'")
            continue
        for placeholder in placeholders:
            if placeholder != "..." and placeholder.lower() in text.lower():
                problems.append(
                    f"{path}: contains the template example value {placeholder!r} "
                    "— report what the tool returned, or one of "
                    f"{', '.join(sorted(UNKNOWN_MARKERS))}"
                )
                break
    return problems


def check_response_targets(data: Any) -> list[str]:
    """Every object acted upon must already appear in the triage or the analysis.

    An executed response naming a host or IOC that no step recorded means
    something was contained on evidence the document does not hold. A context with
    neither section is a direct request: there is nothing to cross-check against,
    and the approval gate is what keeps it human-gated.
    """
    if not isinstance(data, dict):
        return []
    summary = (data.get("responses") or {}).get("responses_summary") or {}
    executed = summary.get("executed_responses")
    if not isinstance(executed, list):
        return []
    if not data.get("triage") and not data.get("analysis"):
        return []

    evidence = json.dumps(
        {key: value for key, value in data.items() if key != "responses"},
        ensure_ascii=False,
    ).lower()

    problems = []
    for index, item in enumerate(executed):
        if not isinstance(item, dict):
            continue
        target = item.get("object")
        if not isinstance(target, str):
            continue
        text = target.strip()
        if not text or text.upper() in UNKNOWN_MARKERS:
            continue
        if text.lower() not in evidence:
            problems.append(
                f"responses.responses_summary.executed_responses[{index}].object: {text!r} "
                "does not appear in the triage or the analysis — an action must not target "
                "evidence that no step recorded"
            )
    return problems


def check_executed_are_authorized(data: Any) -> list[str]:
    """Every executed response must be covered by ``responses.authorization``.

    Matching is on the target object, not the action name: what a human approves
    reads like "aislar el equipo", rarely the tool name.
    """
    if not isinstance(data, dict):
        return []
    responses = data.get("responses")
    if not isinstance(responses, dict):
        return []
    summary = responses.get("responses_summary") or {}
    executed = summary.get("executed_responses")
    if not isinstance(executed, list) or not executed:
        return []

    authorization = responses.get("authorization")
    if not isinstance(authorization, dict):
        return [
            (
                "responses.authorization: absent while responses were executed — the "
                "orchestrator records the human approval before delegating to Tier3"
            )
        ]
    if authorization.get("granted") is not True:
        return ["responses.authorization.granted: not true while responses were executed"]

    approved = json.dumps(authorization.get("approved_actions") or [], ensure_ascii=False).lower()
    problems = []
    for index, item in enumerate(executed):
        if not isinstance(item, dict):
            continue
        target = item.get("object")
        if not isinstance(target, str):
            continue
        text = target.strip()
        if not text or text.upper() in UNKNOWN_MARKERS:
            continue
        if text.lower() not in approved:
            problems.append(
                f"responses.responses_summary.executed_responses[{index}].object: "
                f"{text!r} is not in responses.authorization.approved_actions — the "
                "human approved other objects"
            )
    return problems


def validate_history(data: Any, entry_template: dict[str, Any]) -> list[str]:
    """History is an append-only array of one digest per closed alert.

    Only the digest's top-level fields are fixed; its nested arrays are declared
    empty in the template, so their contents stay free. Tier1 step 4 reads this
    file to decide whether an alert is a repeat, so ``alert_id`` matters most.
    """
    if data == []:
        return []
    if not isinstance(data, list):
        return [f"history: expected an array, got {type(data).__name__}"]

    problems = []
    for index, entry in enumerate(data):
        wrapper = _wrapped_entry_key(entry, entry_template)
        if wrapper:
            problems.append(
                f"history[{index}]: the entry is wrapped in an extra {wrapper!r} object — "
                "unwrap it. Each element of the array IS the digest, with its fields at "
                "the top level"
            )
            continue
        problems += compare(entry, entry_template, f"history[{index}]")
    return problems


def _wrapped_entry_key(entry: Any, entry_template: dict[str, Any]) -> str | None:
    """The key an entry was nested under, when a whole digest sits one level too deep.

    Reported as one line rather than as every declared field being missing: the
    fields are all there, one level down.
    """
    if not isinstance(entry, dict) or len(entry) != 1:
        return None
    key, value = next(iter(entry.items()))
    if isinstance(value, dict) and set(entry_template) & set(value):
        return key
    return None


def validate_workbench(data: Any) -> list[str]:
    """The pending-alerts cache SOC.md reads before anything else.

    The shape is the one declared by ``seed_workbench_list.json``: an object, not
    a bare array, so the freshness metadata cannot be dropped on a rewrite.
    """
    if not isinstance(data, dict) or "alerts" not in data:
        return [
            (
                "workbench_list: expected an object with an 'alerts' array "
                "(see docs/references/seed_workbench_list.json)"
            )
        ]
    if not isinstance(data["alerts"], list):
        return ["workbench_list.alerts: expected an array"]

    problems = [
        f"workbench_list.{key}: missing (see docs/references/seed_workbench_list.json)"
        for key in ("last_updated", "range_days", "limit_reached")
        if key not in data
    ]
    for index, alert in enumerate(data["alerts"]):
        if not isinstance(alert, dict):
            problems.append(f"workbench_list.alerts[{index}]: expected an object")
            continue
        for field in WORKBENCH_ALERT_FIELDS:
            if field not in alert:
                problems.append(f"workbench_list.alerts[{index}].{field}: missing")
    return problems


def report_template_warnings(templates: dict[str, Any]) -> list[str]:
    """Non-fatal drift between report.json and the per-section templates.

    ``Notifier`` reshapes the alert context to match ``report.json``, so if that
    file and the subagent templates disagree the report silently loses fields.
    Reported as a warning: it is a docs problem, not a bad handoff.
    """
    report = _load(REFERENCES / "report.json")
    warnings = []
    for section, template in templates.items():
        if section not in report:
            warnings.append(f"report.json: missing the '{section}' section")
            continue
        warnings += [
            f"report.json vs {SECTION_TEMPLATES[section]}: {problem}"
            for problem in compare(report[section], template, section)
        ]
    return warnings


def _history_entry_template() -> dict[str, Any]:
    """The shape of ONE history entry.

    Two template forms are accepted: an array whose first element is the example
    entry (mirroring the file it describes), or an object keyed ``history_entry``.
    """
    content = _load(REFERENCES / "template_history.json")
    if isinstance(content, list):
        return content[0] if content else {}
    return content.get("history_entry", content)


def state_extras(kind: str, data: Any) -> list[str]:
    """Undeclared keys in one state document. Informational; see ``extra_keys``."""
    if kind == "alert_context" and isinstance(data, dict):
        notes = []
        for section, template in _templates().items():
            if section in data:
                notes += extra_keys(data[section], template, f"alert_context.{section}")
        return notes
    if kind == "history" and isinstance(data, list):
        template = _history_entry_template()
        return [
            note
            for index, entry in enumerate(data)
            for note in extra_keys(entry, template, f"history[{index}]")
        ]
    return []


def check_state(kind: str, data: Any) -> list[str]:
    """Validate one state document by kind. Used by the repo scan and by --check.

    The copied-placeholder check runs for every kind: an example value is just as
    wrong in the history digest, which is the memory Tier1 reads to decide whether
    an alert is a repeat.
    """
    problems = check_copied_placeholders(data, placeholder_values())
    if kind == "alert_context":
        return problems + validate_alert_context(data, _templates())
    if kind == "history":
        return problems + validate_history(data, _history_entry_template())
    if kind == "workbench":
        return problems + validate_workbench(data)
    raise SystemExit(f"Unknown state kind: {kind!r}. Expected one of {sorted(STATE_FILES)}.")


def run_repo_validation() -> int:
    """Validate the tracked contracts, plus any runtime state present locally."""
    problems = []
    missing = []
    for kind, (relative, seed) in sorted(STATE_FILES.items()):
        path = ROOT / relative
        if not path.exists():
            # Not versioned on purpose: absent simply means "no session yet".
            missing.append(relative.as_posix())
            print(f"skipped: {relative.as_posix()} not present (seed: {seed})")
            continue
        data = _load(path)
        problems += check_state(kind, data)
        for note in state_extras(kind, data):
            print(f"note: undeclared key: {note}")

    # One missing file means "no session yet"; all of them missing means the setup
    # has not run. Reported as a warning rather than an error because CI validates
    # a fresh checkout, where their absence is the expected state.
    if missing and len(missing) == len(STATE_FILES):
        print(
            "warning: no state file exists. On a fresh clone that means setup has not run yet; "
            "run ./setup.sh (or ./setup.ps1) to seed them from docs/references/seed_*."
        )

    for warning in report_template_warnings(_templates()):
        print(f"warning: {warning}")

    if problems:
        print(f"\n{len(problems)} problem(s) found:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("Harness state matches the reference templates.")
    return 0


def run_check(kind: str) -> int:
    """Validate a JSON document read from stdin, before it is written to disk.

    This is the hook the OpenCode plugin calls on every write to a state file, so
    a malformed handoff is refused at the moment it happens — with the reason —
    instead of surfacing later as an empty report.
    """
    # A leading BOM is stripped rather than rejected: it must not make the document
    # look malformed.
    raw = sys.stdin.read().lstrip("﻿")
    try:
        data = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError as exc:
        print(f"not valid JSON: {exc}", file=sys.stderr)
        return 1
    if data is None:
        print(
            "empty content: write the seed shape instead of an empty file",
            file=sys.stderr,
        )
        return 1

    problems = check_state(kind, data)
    if problems:
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    # Accepted, but say what was added: the write lands either way, and a note
    # here is what keeps an undeclared field from becoming a silent structure.
    for note in state_extras(kind, data):
        print(f"note: undeclared key accepted: {note}", file=sys.stderr)
    return 0


def run_self_test() -> int:
    """Exercise the comparison rules without touching the repo state."""
    template = {"triage": {"id": "WB-1", "triage_summary": {"false_positive": False}}}
    templates = {"triage": template["triage"]}

    assert validate_alert_context({}, templates) == [], "an empty context must be valid"
    assert validate_alert_context({"triage": template["triage"]}, templates) == []

    missing = validate_alert_context({"triage": {"id": "WB-1"}}, templates)
    assert missing == ["alert_context.triage.triage_summary: missing (required by the template)"], (
        missing
    )

    # An undeclared field is accepted: the agents are allowed to record what they
    # observed, and the report renders it. It is reported separately, not refused.
    added = {"triage": {**template["triage"], "invented": 1}}
    assert validate_alert_context(added, templates) == [], validate_alert_context(added, templates)
    notes = extra_keys(added["triage"], templates["triage"], "alert_context.triage")
    assert notes == ["alert_context.triage.invented"], notes

    # A whole new top-level section is still refused: it means the agent did not
    # know where something belonged, and the answer is a field in its own section.
    unknown = validate_alert_context({"nope": {}}, templates)
    assert unknown == ["alert_context.nope: unknown section"], unknown

    wrong_type = compare({"a": []}, {"a": {}}, "root")
    assert wrong_type == ["root.a: expected an object, got list"], wrong_type

    # A declared key missing from a list item is still a problem; an added one is not.
    items = compare([{"x": 1}, {"y": 2}], [{"x": 0}], "root")
    assert items == ["root[1].x: missing (required by the template)"], items
    assert extra_keys([{"x": 1}, {"y": 2}], [{"x": 0}], "root") == ["root[1].y"]

    # --- workbench: the shape the seed declares ----------------------------
    envelope = {
        "last_updated": None,
        "range_days": 30,
        "limit_reached": False,
        "alerts": [],
    }
    assert validate_workbench(envelope) == []
    assert validate_workbench({**envelope, "alerts": [{"id": "WB-1"}]})[0].endswith(
        "model: missing"
    )
    # A bare array loses the envelope fields, so it must be rejected.
    assert validate_workbench([{"id": "WB-1"}])[0].startswith("workbench_list: expected an object")
    assert validate_workbench({"alerts": []}) == [
        "workbench_list.last_updated: missing (see docs/references/seed_workbench_list.json)",
        "workbench_list.range_days: missing (see docs/references/seed_workbench_list.json)",
        "workbench_list.limit_reached: missing (see docs/references/seed_workbench_list.json)",
    ]

    # --- history: one digest per closed alert -------------------------------
    entry = {"alert_id": "WB-1", "endpoints": []}
    assert validate_history([], entry) == []
    assert validate_history([entry], entry) == []
    assert validate_history([{"alert_id": "WB-1"}], entry) == [
        "history[0].endpoints: missing (required by the template)"
    ]
    # Nested arrays are declared empty, so their contents stay free.
    assert validate_history([{**entry, "endpoints": [{"whatever": 1}]}], entry) == []
    assert validate_history("nope", entry) == ["history: expected an array, got str"]

    # --- anti-fabrication --------------------------------------------------
    placeholders = {
        "WB-9002-20220906-00025",
        "2022-09-06T02:49:33Z",
        "sender@example.com",
        "...",
    }

    assert check_copied_placeholders({"triage": {"id": "WB-1-20260731-00001"}}, placeholders) == []
    copied = check_copied_placeholders({"triage": {"id": "WB-9002-20220906-00025"}}, placeholders)
    assert len(copied) == 1 and "template example value" in copied[0], copied
    # Also caught inside a longer string (a report path, a note...).
    nested = check_copied_placeholders(
        {"h": [{"report_file": "outputs/WB-9002-20220906-00025.html"}]}, placeholders
    )
    assert len(nested) == 1, nested
    assert check_copied_placeholders({"a": {"summary": "..."}}, placeholders) == [
        "a.summary: still the template placeholder '...'"
    ]
    # A real summary that merely contains an ellipsis is not a placeholder.
    assert (
        check_copied_placeholders({"a": {"summary": "se detecto... y se contuvo"}}, {"..."}) == []
    )
    # Declared gaps are always acceptable.
    assert check_copied_placeholders({"a": {"cve": "NOT_COLLECTED"}}, placeholders) == []

    # A detection-rule GUID from the sample payload is a real Vision One identifier
    # that a live alert can carry, so it must not be treated as a placeholder.
    derived = placeholder_values()
    assert "b23bc903-ecfb-4052-90a0-167adb93abb7" not in derived, "real rule GUIDs must pass"
    assert "00000000-0000-0000-0000-000000000000" in derived, "the zeroed GUID is a placeholder"
    assert "WB-9002-20220906-00025" in derived

    # A digest nested one level deep must be named as such, not reported as every
    # field being absent.
    entry_template = _history_entry_template()
    assert "alert_id" in entry_template, "the template must describe ONE entry"
    wrapped = validate_history([{"history_entry": {"alert_id": "WB-1"}}], entry_template)
    assert len(wrapped) == 1, wrapped
    assert "wrapped in an extra 'history_entry' object" in wrapped[0], wrapped[0]
    # A real entry missing fields still reports them one by one.
    assert len(validate_history([{"alert_id": "WB-1"}], entry_template)) > 1

    acted = {
        "triage": {"indicators": [{"value": "HOST-9"}]},
        "responses": {
            "responses_summary": {
                "executed_responses": [{"action": "isolate_endpoint", "object": "HOST-9"}]
            }
        },
    }
    assert check_response_targets(acted) == [], check_response_targets(acted)

    # The human approval is data, so it can be checked: what ran must be what was
    # approved. Absent approval with executed responses is the dangerous case.
    authorized = {
        "responses": {
            "authorization": {
                "granted": True,
                "approved_actions": [{"action": "isolate", "object": "HOST-9"}],
            },
            "responses_summary": {"executed_responses": [{"object": "HOST-9"}]},
        }
    }
    assert check_executed_are_authorized(authorized) == []
    unapproved = {
        "responses": {
            "authorization": {
                "granted": True,
                "approved_actions": [{"action": "isolate", "object": "HOST-9"}],
            },
            "responses_summary": {"executed_responses": [{"object": "HOST-7"}]},
        }
    }
    assert len(check_executed_are_authorized(unapproved)) == 1
    no_auth = {"responses": {"responses_summary": {"executed_responses": [{"object": "HOST-9"}]}}}
    assert len(check_executed_are_authorized(no_auth)) == 1
    refused = {
        "responses": {
            "authorization": {"granted": False, "approved_actions": []},
            "responses_summary": {"executed_responses": [{"object": "HOST-9"}]},
        }
    }
    assert len(check_executed_are_authorized(refused)) == 1
    # Nothing executed yet: the orchestrator wrote the section, Tier3 has not run.
    assert check_executed_are_authorized({"responses": {"responses_summary": {}}}) == []

    invented = {**acted, "triage": {"indicators": [{"value": "HOST-1"}]}}
    assert len(check_response_targets(invented)) == 1, check_response_targets(invented)
    # An unknown marker as the target is a declared gap, not an invented object.
    unknown_target = {
        **acted,
        "triage": {},
        "responses": {"responses_summary": {"executed_responses": [{"object": "N/A"}]}},
    }
    assert check_response_targets(unknown_target) == []

    # A direct request has no alert to cross-check against: the operator asked for
    # it, and the approval gate — not this check — is what keeps it human-gated.
    direct = {
        "responses": {
            "responses_summary": {
                "executed_responses": [{"action": "isolate_endpoint", "object": "DESKTOP-7"}]
            }
        }
    }
    assert check_response_targets(direct) == [], check_response_targets(direct)
    # But once an alert IS being managed, an unrelated target is still refused.
    assert len(check_response_targets({**direct, "triage": {"indicators": []}})) == 1

    print("Self-test passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="validate the checker, not the repo state",
    )
    parser.add_argument(
        "--check",
        choices=sorted(STATE_FILES),
        help="validate a JSON document read from stdin as this kind of state file",
    )
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    if args.check:
        return run_check(args.check)
    return run_repo_validation()


if __name__ == "__main__":
    raise SystemExit(main())
