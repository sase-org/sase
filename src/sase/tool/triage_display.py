"""Shared, store-only presentation for durable ToolRun failure triage."""

from __future__ import annotations

from collections import Counter
from typing import Any


_CLASS_ORDER = ("new", "unknown", "known", "flaky")
_COMPACT_CAPS = {"new": 10, "unknown": 10, "known": 3, "flaky": 3}


def footer_triage_lines(
    triage: dict[str, Any] | None, *, exit_code: int
) -> tuple[list[str], str | None]:
    """Return compact footer detail and its final verdict line.

    The caller deliberately prints the existing ``tool show`` pointer between
    these values, preserving its established location while keeping a verdict
    as the final line of a compact footer.
    """

    if not isinstance(triage, dict):
        return [], None
    diagnostics = _strings(triage.get("diagnostics"))
    if not triage.get("triaged") and diagnostics:
        return [f"triage unavailable: {diagnostics[0]}"], None
    items = _dicts(triage.get("items"))
    lines = [_stage_line(stage, items) for stage in _dicts(triage.get("stages"))]
    for class_name in _CLASS_ORDER:
        selected = [item for item in items if _item_class(item) == class_name]
        for item in selected[: _COMPACT_CAPS[class_name]]:
            lines.append(_item_line(item))
    run_facts = triage.get("run_facts")
    if isinstance(run_facts, dict) and run_facts.get("repeat_of_run_id"):
        lines.append(f"REPEAT of {run_facts['repeat_of_run_id']}")
    return lines, _verdict_line(triage, items, exit_code)


def show_triage_lines(triage: object) -> list[str]:
    """Return the human ``TRIAGE`` section for an ungated explicit view."""

    if not isinstance(triage, dict):
        return []
    lines = ["TRIAGE"]
    kind = triage.get("failure_kind")
    verdict = triage.get("verdict")
    lines.append(f"  KIND     {kind or '—'}")
    lines.append(f"  VERDICT  {verdict or '—'}")
    if triage.get("verdict_reason"):
        lines.append(f"  REASON   {triage['verdict_reason']}")
    if triage.get("remedy"):
        lines.append(f"  REMEDY   {triage['remedy']}")
    for stage in _dicts(triage.get("stages")):
        extraction = stage.get("extraction_status") or "—"
        decision = stage.get("decision")
        decision_text = "—"
        if isinstance(decision, dict):
            decision_text = str(decision.get("decision") or "—")
        lines.append(
            "  STAGE    "
            f"{stage.get('stage_key') or '—'}  extraction={extraction} "
            f"decision={decision_text}"
        )
    items = _dicts(triage.get("items"))
    if items:
        lines.append("  CLASS    STAGE  ITEM  EVIDENCE  OWNER")
        for item in sorted(items, key=_item_sort_key):
            lines.append(
                "  "
                f"{(_item_class(item) or '—').upper():<8} "
                f"{item.get('stage_key') or '—'}  {item.get('display') or item.get('item_id') or '—'}"
                f"  {_evidence_summary(item)}  {_owner_summary(item)}"
            )
    for diagnostic in _strings(triage.get("diagnostics")):
        lines.append(f"  DIAG     {diagnostic}")
    return lines


def _stage_line(stage: dict[str, Any], items: list[dict[str, Any]]) -> str:
    counts = Counter(
        _item_class(item)
        for item in items
        if item.get("stage_key") == stage.get("stage_key")
    )
    details = " ".join(
        f"{count} {name.upper()}" for name, count in sorted(counts.items()) if name
    )
    extraction = str(stage.get("extraction_status") or "unknown")
    decision = stage.get("decision")
    marker = ""
    if isinstance(decision, dict):
        value = str(decision.get("decision") or "")
        if value:
            marker = f" {value}d" if value in {"continue", "stop"} else f" {value}"
    suffix = f" {details}" if details else f" {extraction}"
    return f"triage {stage.get('stage_key') or '—'}:{suffix}{marker}"


def _item_line(item: dict[str, Any]) -> str:
    class_name = (_item_class(item) or "unknown").upper()
    display = str(item.get("display") or item.get("item_id") or "—")
    return (
        f"{class_name} {item.get('stage_key') or '—'}: {display}"
        f" — {_evidence_summary(item)}; {_owner_summary(item)}"
    )


def _verdict_line(
    triage: dict[str, Any], items: list[dict[str, Any]], exit_code: int
) -> str | None:
    verdict = triage.get("verdict")
    if not verdict or str(verdict) == "pass":
        return None
    counts = Counter(_item_class(item) for item in items)
    summary = ", ".join(
        f"{counts[name]} {name.upper()}" for name in _CLASS_ORDER if counts[name]
    )
    tail = f" — {summary}" if summary else ""
    return f"verdict: {verdict}{tail}; exit {exit_code}"


def _item_class(item: dict[str, Any]) -> str:
    label = item.get("label")
    return str(label.get("class") or "") if isinstance(label, dict) else ""


def _evidence_summary(item: dict[str, Any]) -> str:
    label = item.get("label")
    if not isinstance(label, dict):
        return "no label"
    evidence = label.get("evidence")
    if not isinstance(evidence, dict):
        return "no evidence"
    witnesses = _strings(evidence.get("witness_run_ids"))
    if witnesses:
        return f"witness {witnesses[0]}"
    reasons = _strings(evidence.get("rejection_reasons"))
    return reasons[0] if reasons else "recorded evidence"


def _owner_summary(item: dict[str, Any]) -> str:
    label = item.get("label")
    if not isinstance(label, dict):
        return "no owner"
    owners = label.get("possible_owners")
    if not isinstance(owners, list) or not owners:
        return "no owner"
    first = owners[0]
    if isinstance(first, dict):
        owner = str(first.get("id") or first.get("node_id") or "")
        if owner:
            return f"possible owner {owner}"
    return "possible owner"


def _item_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    class_name = _item_class(item)
    try:
        index = _CLASS_ORDER.index(class_name)
    except ValueError:
        index = len(_CLASS_ORDER)
    return index, str(item.get("item_id") or "")


def _dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, dict)]


def _strings(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item)]


__all__ = ["footer_triage_lines", "show_triage_lines"]
