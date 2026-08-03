#!/usr/bin/env python3
"""
Render the SOC report from the alert context, deterministically.

The report is the record a human archives, so it is built by code rather than
written by the model: the same context always produces the same document and every
value is HTML-escaped. Recognised areas (header, detection card, timeline,
indicators, impact scope, entities, MITRE mapping) keep a fixed layout; every other
key is rendered as generic labelled blocks, so a field nobody declared still
appears. A template binds to the view model built here, not to the Vision One
payload — see ``README.md`` for its shape.

Usage (through ``uv``; Jinja2 is fetched per invocation so the harness keeps no
Python project of its own):
    uv run --with jinja2 --no-project scripts/render_report.py
    uv run --with jinja2 --no-project scripts/render_report.py --template mi.html
    uv run --with jinja2 --no-project scripts/render_report.py --check-template mi.html
    uv run --with jinja2 --no-project scripts/render_report.py --self-test

Exit code 0 = the report was written (or the checks passed), 1 = it was not.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REFERENCES = ROOT / "docs" / "references"
DEFAULT_CONTEXT = ROOT / "context" / "alert_context.json"
DEFAULT_TEMPLATE = ROOT / "docs" / "reports" / "templates" / "soc_report.html"
OUTPUT_DIR = ROOT / "docs" / "reports" / "outputs"
LABELS_FILE = REFERENCES / "report_labels.json"

# Declared by the agents when a value could not be obtained. Rendered as-is: a
# stated gap is information, and hiding it would make the report look complete.
MARKERS = frozenset({"N/A", "NOT_COLLECTED", "UNAVAILABLE"})

MISSING = "N/A"

# Paths consumed by a recognised area. Everything not listed here surfaces in the
# generic blocks, which is what keeps an unexpected field visible instead of lost.
CONSUMED = {
    "triage": {
        "id",
        "status",
        "workbenchLink",
        "model",
        "description",
        "score",
        "severity",
        "createdDateTime",
        "incidentId",
        "impactScope",
        "indicators",
        "matchedRules",
        "triage_status",
        "triage_date",
        "triage_summary",
    },
    "analysis": {"analysis_status", "analysis_date", "analysis_summary"},
    "responses": {
        "authorization",
        "responses_status",
        "responses_date",
        "responses_summary",
    },
}

# Severity drives the colour of the header badge. Anything unknown renders neutral.
SEVERITY_TONES = {
    "critical": "critical",
    "crítica": "critical",
    "critica": "critical",
    "high": "high",
    "alta": "high",
    "medium": "medium",
    "media": "medium",
    "low": "low",
    "baja": "low",
    "info": "low",
    "informational": "low",
}


def load_json(path: Path, *, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if default is not None:
            return default
        raise SystemExit(f"Missing file: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}") from None


def labels() -> dict[str, str]:
    """Optional key -> human label map. Incomplete on purpose: see ``humanise``."""
    return load_json(LABELS_FILE, default={})


def humanise(key: str) -> str:
    """A readable label for a key nobody declared.

    ``desktopCount`` -> ``Desktop count``, ``analysis_status`` -> ``Analysis
    status``. A field added by a tool or by an agent is presentable without
    anyone having to register it first.
    """
    spaced = []
    for index, char in enumerate(key.replace("_", " ").replace("-", " ")):
        if char.isupper() and index and not key[index - 1].isupper():
            spaced.append(" ")
        spaced.append(char)
    text = "".join(spaced).strip()
    text = " ".join(text.split())
    return text[:1].upper() + text[1:] if text else key


def label_for(key: str, mapping: dict[str, str]) -> str:
    return mapping.get(key) or humanise(key)


def is_empty(value: Any) -> bool:
    """Whether a value carries nothing worth a row. Zero and False do carry."""
    return value is None or value == "" or value == [] or value == {}


def as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if value is None:
        return MISSING
    return str(value)


def block(key: str, value: Any, mapping: dict[str, str]) -> dict[str, Any] | None:
    """One labelled value, classified so the template can style it consistently.

    ``kind`` is the whole vocabulary a template has to handle: text, number,
    bool, link, chips (a list of short scalars), list (a list of longer ones),
    pairs (a flat object) and table (a list of objects, carrying ``columns``,
    ``rows`` and ``widths`` instead of ``value``). Anything deeper is serialised
    rather than dropped.
    """
    if is_empty(value):
        return None
    label = label_for(key, mapping)

    if isinstance(value, bool):
        return {"label": label, "kind": "bool", "value": value, "text": as_text(value)}
    if isinstance(value, (int, float)):
        return {
            "label": label,
            "kind": "number",
            "value": value,
            "text": as_text(value),
        }
    if isinstance(value, str):
        kind = "link" if value.startswith(("http://", "https://")) else "text"
        return {"label": label, "kind": kind, "value": value, "text": value}
    if isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            items = [as_text(v) for v in value]
            # Chips are for tokens — technique ids, tags, hostnames. A list of
            # findings, each a sentence long, rendered as chips is a wall of pills
            # that cannot be scanned; those are a list.
            kind = "chips" if all(len(item) <= 32 for item in items) else "list"
            return {"label": label, "kind": kind, "value": items}
        records = [item for item in value if isinstance(item, dict)]
        if records:
            return {"label": label, "kind": "table", **table_of(records, mapping)}
        return {
            "label": label,
            "kind": "text",
            "value": json.dumps(value, ensure_ascii=False),
        }
    if isinstance(value, dict):
        return {"label": label, "kind": "pairs", "value": flatten_pairs(value, mapping)}
    return {"label": label, "kind": "text", "value": as_text(value)}


def cell_text(value: Any) -> str:
    """One value as the single string a cell or a pair shows."""
    if is_empty(value):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return as_text(value)


def flatten_pairs(node: dict[str, Any], mapping: dict[str, str]) -> list[dict[str, str]]:
    """A dict as ordered label/text pairs, serialising anything nested."""
    pairs = []
    for key in order_keys(node, mapping):
        if is_empty(node[key]):
            continue
        pairs.append({"label": label_for(key, mapping), "text": cell_text(node[key])})
    return pairs


def column_widths(columns: list[str], rows: list[list[str]]) -> list[str]:
    """A width per column, from how much text each one actually holds.

    The template lays generic tables out with ``table-layout: fixed`` so a long
    hash cannot crush the columns beside it, and fixed layout splits the row
    evenly unless it is told otherwise — which starves the one free-text column
    (``detalle``, ``evidencia``, ``motivo``) while ``tipo`` keeps a fifth of the
    row empty. The weight is the longest cell, capped: past the cap a column can
    only wrap, so a 400-character detail should not claim ten times the room of a
    40-character one.

    ``pad`` is what keeps a short column from being starved instead: the cell has
    horizontal padding that no share of the row pays for, and a ``tipo`` column
    that comes out one character too narrow prints ``file_sha25`` with a lone
    ``6`` under it. Added to every column, so it also keeps one long column from
    dominating a table of otherwise short ones.
    """
    cap, pad = 28, 4
    weights = [
        pad + min(cap, max([len(column)] + [len(row[index]) for row in rows]))
        for index, column in enumerate(columns)
    ]
    total = sum(weights) or 1
    return [f"{weight * 100 / total:.4g}%" for weight in weights]


def table_of(records: list[dict[str, Any]], mapping: dict[str, str]) -> dict[str, Any]:
    """A list of records as one table: shared columns, one aligned row each.

    Columns and not per-row pairs: five IOC verdicts printed as five label/value
    lists is the same five labels repeated five times, and the values no longer
    line up to be compared. A field a record omits leaves its cell empty so the
    rest of the row stays under its own heading.
    """
    keys: list[str] = []
    for record in records:
        for key in order_keys(record, mapping):
            if key not in keys and not is_empty(record[key]):
                keys.append(key)
    columns = [label_for(key, mapping) for key in keys]
    rows = [[cell_text(record.get(key)) for key in keys] for record in records]
    return {"columns": columns, "rows": rows, "widths": column_widths(columns, rows)}


def order_keys(node: dict[str, Any], mapping: dict[str, str]) -> list[str]:
    """Declared keys in their declared order, then the rest alphabetically.

    Deterministic ordering is what makes two reports of the same kind
    comparable; without it the same alert can render differently twice.
    """
    declared = [key for key in mapping if key in node]
    rest = sorted(key for key in node if key not in mapping)
    return declared + rest


def blocks_for(node: Any, skip: set[str], mapping: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(node, dict):
        return []
    found = []
    for key in order_keys(node, mapping):
        if key in skip:
            continue
        rendered = block(key, node[key], mapping)
        if rendered:
            found.append(rendered)
    return found


def entity_view(entity: Any, mapping: dict[str, str]) -> dict[str, Any]:
    """One impact-scope entity. Hosts carry a name and IPs; the rest, a value."""
    if not isinstance(entity, dict):
        return {"type": MISSING, "title": as_text(entity), "detail": "", "extras": []}
    kind = as_text(entity.get("entityType") or MISSING)
    value = entity.get("entityValue")
    if isinstance(value, dict):
        title = as_text(value.get("name") or value.get("guid") or MISSING)
        ips = value.get("ips")
        detail = ", ".join(as_text(ip) for ip in ips) if isinstance(ips, list) and ips else ""
        # Only what the card already shows is dropped, and it is matched by key:
        # the labels are translated, so matching those printed the name and the IPs
        # a second time, the IPs as raw JSON. A `guid` that did not become the
        # title is still information, so it stays.
        shown = {"name"} if value.get("name") else {"guid"}
        if detail:
            shown.add("ips")
        extras = flatten_pairs({k: v for k, v in value.items() if k not in shown}, mapping)
    else:
        title = as_text(value if value is not None else MISSING)
        detail = ""
        extras = []
    return {"type": kind, "title": title, "detail": detail, "extras": extras}


def timeline_step(
    *,
    tier: str,
    title: str,
    tone: str,
    node: Any,
    section: str,
    date_key: str,
    status_key: str | None,
    summary_key: str,
    mapping: dict[str, str],
) -> dict[str, Any]:
    """One tier of the handling timeline, tolerant of a section that is absent.

    ``extras`` here is what the step itself adds beyond the recognised keys of its
    section — not the alert's own fields, which the header already shows.
    """
    node = node if isinstance(node, dict) else {}
    summary = node.get(summary_key)
    summary = summary if isinstance(summary, dict) else {}
    consumed = CONSUMED[section] | {date_key, summary_key} | ({status_key} if status_key else set())
    body = blocks_for(summary, {"summary", "executed_responses"}, mapping)
    # Scalars fit the one-line facts row; the analysis content (IOC verdicts,
    # MITRE techniques, suggested responses) needs the room below the summary.
    scalar = {"text", "number", "bool", "link"}
    return {
        "tier": tier,
        "title": title,
        "tone": tone,
        "date": as_text(node.get(date_key) or MISSING),
        "status": as_text(node.get(status_key) or MISSING) if status_key else "",
        "summary": as_text(summary.get("summary") or MISSING),
        "facts": [b for b in body if b["kind"] in scalar],
        "details": [b for b in body if b["kind"] not in scalar],
        "extras": blocks_for(node, consumed, mapping),
    }


def build_view(context: Any, *, generated_at: str) -> dict[str, Any]:
    """Turn an alert context into everything a template needs, and nothing else."""
    mapping = labels()
    context = context if isinstance(context, dict) else {}
    triage = context.get("triage") if isinstance(context.get("triage"), dict) else {}
    analysis = context.get("analysis") if isinstance(context.get("analysis"), dict) else {}
    responses = context.get("responses") if isinstance(context.get("responses"), dict) else {}

    impact = triage.get("impactScope") if isinstance(triage.get("impactScope"), dict) else {}
    counts = [
        {"label": label_for(key, mapping), "value": as_text(impact[key])}
        for key in order_keys(impact, mapping)
        if key.endswith("Count")
    ]
    entities = impact.get("entities") if isinstance(impact.get("entities"), list) else []

    indicators = triage.get("indicators") if isinstance(triage.get("indicators"), list) else []
    indicator_rows = [
        {
            "type": as_text(item.get("type") or MISSING),
            "field": as_text(item.get("field") or MISSING),
            "value": as_text(item.get("value") if item.get("value") is not None else MISSING),
        }
        for item in indicators
        if isinstance(item, dict)
    ]

    mitre = []
    rules = triage.get("matchedRules") if isinstance(triage.get("matchedRules"), list) else []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        filters = rule.get("matchedFilters")
        mitre.append(
            {
                "rule": as_text(rule.get("name") or MISSING),
                "filters": [
                    {
                        "name": as_text(item.get("name") or MISSING),
                        "techniques": [
                            as_text(t) for t in (item.get("mitreTechniqueIds") or []) if t
                        ],
                        "matched": as_text(item.get("matchedDateTime") or MISSING),
                    }
                    for item in (filters if isinstance(filters, list) else [])
                    if isinstance(item, dict)
                ],
            }
        )

    executed = []
    summary_node = responses.get("responses_summary")
    if isinstance(summary_node, dict) and isinstance(summary_node.get("executed_responses"), list):
        for item in summary_node["executed_responses"]:
            if not isinstance(item, dict):
                continue
            executed.append(
                {
                    "action": as_text(item.get("action") or MISSING),
                    "result": as_text(item.get("result") or MISSING),
                    "reason": as_text(item.get("reason") or MISSING),
                    "object": as_text(item.get("object") or MISSING),
                    # Filtered by key, not by label: the labels are translated, so
                    # matching them repeated every field the header already shows.
                    "extras": flatten_pairs(
                        {
                            k: v
                            for k, v in item.items()
                            if k not in {"action", "result", "reason", "object"}
                        },
                        mapping,
                    ),
                }
            )

    # The human authorization is a recognised area, not a generic block: it is the
    # evidence that the containment gate was passed, and a JSON blob does not read
    # as evidence. Its nested list gets the same row cards as the executions.
    auth = responses.get("authorization")
    auth = auth if isinstance(auth, dict) else {}
    approved = auth.get("approved_actions")
    approved = [a for a in (approved if isinstance(approved, list) else []) if isinstance(a, dict)]
    authorization = {
        "present": bool(auth),
        "facts": flatten_pairs({k: v for k, v in auth.items() if k != "approved_actions"}, mapping),
        "approved": table_of(approved, mapping) if approved else None,
    }

    severity = as_text(triage.get("severity") or MISSING)
    link = triage.get("workbenchLink")
    view: dict[str, Any] = {
        "meta": {
            "alert_id": as_text(triage.get("id") or MISSING),
            "severity": severity,
            "severity_tone": SEVERITY_TONES.get(severity.strip().lower(), "neutral"),
            "status": as_text(triage.get("status") or MISSING),
            "model": as_text(triage.get("model") or MISSING),
            "description": as_text(triage.get("description") or MISSING),
            "score": as_text(triage.get("score") if triage.get("score") is not None else MISSING),
            "incident_id": as_text(triage.get("incidentId") or MISSING),
            "created": as_text(triage.get("createdDateTime") or MISSING),
            "workbench_link": link if isinstance(link, str) and link.startswith("http") else "",
            "generated_at": generated_at,
        },
        "impact": {
            "counts": counts,
            "entities": [entity_view(e, mapping) for e in entities],
        },
        "indicators": indicator_rows,
        "mitre": mitre,
        "authorization": authorization,
        "executed": executed,
        "timeline": [
            timeline_step(
                tier="Tier 1",
                title="Triage y clasificación",
                tone="tier1",
                node=triage,
                section="triage",
                date_key="triage_date",
                status_key="triage_status",
                summary_key="triage_summary",
                mapping=mapping,
            ),
            timeline_step(
                tier="Tier 2",
                title="Investigación y análisis",
                tone="tier2",
                node=analysis,
                section="analysis",
                date_key="analysis_date",
                status_key="analysis_status",
                summary_key="analysis_summary",
                mapping=mapping,
            ),
            timeline_step(
                tier="Tier 3",
                title="Acciones de respuesta",
                tone="tier3",
                node=responses,
                section="responses",
                date_key="responses_date",
                status_key="responses_status",
                summary_key="responses_summary",
                mapping=mapping,
            ),
        ],
        "extras": [],
    }

    # Sections the layout does not know about, so a whole area an agent decided to
    # add stays visible. The leftovers of the three known sections are NOT collected
    # here: each timeline step already renders its own, and doing both printed every
    # unrecognised field twice — once in the step, once in a card at the end.
    for name in sorted(context):
        if name in CONSUMED:
            continue
        remaining = blocks_for(context[name], set(), mapping)
        if not remaining and not is_empty(context[name]):
            single = block(name, context[name], mapping)
            remaining = [single] if single else []
        if remaining:
            view["extras"].append({"title": label_for(name, mapping), "blocks": remaining})

    return view


def environment() -> Any:
    """A sandboxed, auto-escaping Jinja environment.

    Both settings are load-bearing: alert descriptions, paths and IOCs are
    attacker-influenceable strings, and the sandbox keeps a user-supplied template
    from reaching through attributes into the interpreter.
    """
    try:
        from jinja2 import StrictUndefined
        from jinja2.sandbox import SandboxedEnvironment
    except ModuleNotFoundError:
        raise SystemExit(
            "Jinja2 is not available. Run this through uv so it is fetched per "
            "invocation:\n"
            "    uv run --with jinja2 --no-project scripts/render_report.py"
        ) from None

    env = SandboxedEnvironment(autoescape=True, undefined=StrictUndefined)
    env.filters["label"] = humanise
    return env


def render(template_path: Path, view: dict[str, Any]) -> str:
    env = environment()
    try:
        template = env.from_string(template_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Missing template: {template_path}") from None
    return template.render(report=view)


def sample_view() -> dict[str, Any]:
    """A view built from the reference document, plus fields nobody declared.

    Used to check a template: it must survive both the documented shape and
    undeclared extras.
    """
    context = load_json(REFERENCES / "report.json")
    if isinstance(context.get("triage"), dict):
        context["triage"]["undeclared_field"] = "undeclared field value"
    context["undeclared_section"] = {"finding": "undeclared section value"}
    return build_view(context, generated_at="1970-01-01T00:00:00Z")


def run_check_template(template_path: Path) -> int:
    """Dry-render a template. Nothing is written; only the template is exercised."""
    html = render(template_path, sample_view())
    if "<html" not in html.lower():
        print(
            f"{template_path}: rendered output is not an HTML document.",
            file=sys.stderr,
        )
        return 1
    print(f"{template_path.name}: renders cleanly ({len(html)} bytes).")
    return 0


def run_self_test() -> int:
    """Check the renderer itself: escaping, tolerance, determinism, extras."""
    problems: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    # An empty context must still produce a report, not an exception.
    empty = build_view({}, generated_at="X")
    expect(empty["meta"]["alert_id"] == MISSING, "an empty context should render markers")
    expect(len(empty["timeline"]) == 3, "the timeline must always have its three tiers")

    # Junk in place of a section must not crash the renderer.
    junk = build_view({"triage": "no soy un objeto", "analysis": []}, generated_at="X")
    expect(
        junk["meta"]["status"] == MISSING,
        "a non-object section should degrade to markers",
    )

    # Unknown fields and unknown sections have to survive into the extras.
    view = sample_view()
    flat = json.dumps(view, ensure_ascii=False)
    expect("undeclared field value" in flat, "an unknown field must reach the extras")
    expect(
        "undeclared section value" in flat,
        "an unknown section must reach the extras",
    )
    # And it must survive all the way into the document, not only the view model.
    rendered = render(DEFAULT_TEMPLATE, view)
    expect("undeclared field value" in rendered, "an unknown field must reach the report")
    expect("Undeclared field" in rendered, "its label should be humanised")

    # Ordering is what makes two reports comparable.
    expect(
        build_view(load_json(REFERENCES / "report.json"), generated_at="X")
        == build_view(load_json(REFERENCES / "report.json"), generated_at="X"),
        "the same context must always produce the same view",
    )

    # Escaping is the reason this is code and not a prompt.
    hostile = build_view(
        {"triage": {"description": "<script>alert(1)</script>", "id": "WB-1"}},
        generated_at="X",
    )
    html = render(DEFAULT_TEMPLATE, hostile)
    expect("<script>alert(1)</script>" not in html, "markup in a value must be escaped")
    expect("&lt;script&gt;" in html, "the escaped form should be present")

    # Values the agents use to declare a gap must survive verbatim.
    marked = build_view({"triage": {"id": "NOT_COLLECTED"}}, generated_at="X")
    expect(marked["meta"]["alert_id"] == "NOT_COLLECTED", "markers must not be rewritten")

    if problems:
        print(f"{len(problems)} problem(s) found:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("Self-test passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, default=DEFAULT_CONTEXT)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument(
        "--out", type=Path, help="output file (default: docs/reports/outputs/<id>.html)"
    )
    parser.add_argument("--check-template", type=Path, help="dry-render a template and exit")
    parser.add_argument("--self-test", action="store_true", help="check the renderer itself")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    if args.check_template:
        return run_check_template(args.check_template)

    context = load_json(args.context)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    view = build_view(context, generated_at=generated_at)

    alert_id = view["meta"]["alert_id"]
    if alert_id in MARKERS:
        print(
            f"{args.context} has no triage.id, so the report has no name. "
            "Run the triage first, or pass --out explicitly.",
            file=sys.stderr,
        )
        return 1

    out = args.out or OUTPUT_DIR / f"{alert_id}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(args.template, view), encoding="utf-8")
    print(out.relative_to(ROOT).as_posix() if out.is_relative_to(ROOT) else out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
