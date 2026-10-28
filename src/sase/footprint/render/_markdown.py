"""Compact agent-ready Markdown for Footprint reports and cards."""

from __future__ import annotations

from typing import Any

from sase.footprint.render._report import evidence_sentence


def report_markdown(report: dict[str, Any], lens: str) -> str:
    """Return one-table-per-lens Markdown with evidence and backticked IDs."""
    header = dict(report.get("header", {}))
    tiles = dict(report.get("tiles", {}))
    lines = [f"# Footprint · {lens} · {header.get('actor', 'you')}"]
    lines.append("")
    window = header.get("window_days")
    window_label = "all" if window is None else f"{window}d"
    lines.append(
        f"Window {header.get('window_start', '—')} → {header.get('window_end', '—')}"
        f" ({window_label}) · recording since {header.get('recording_since') or '—'}"
    )
    lines.append(
        f"Used {tiles.get('used', 0)}/{tiles.get('total', 0)}"
        f" · candidates {tiles.get('candidates', 0)}"
        f"{' (preview)' if tiles.get('candidates_preview') else ''}"
        f" · rare by design {tiles.get('rare_by_design', 0)}"
        f" · agent-only {tiles.get('agent_only', 0)}"
        f" · not measured {tiles.get('not_measured', 0)}"
    )
    lines.append("")
    if lens == "map":
        lines.extend(_area_table(report.get("areas", [])))
    elif lens == "coverage":
        lines.extend(_coverage_table(report.get("coverage", [])))
    else:
        lines.extend(_row_table(report.get("rows", []), header))
    return "\n".join(lines).rstrip() + "\n"


def _area_table(areas: Any) -> list[str]:
    lines = [
        "## Areas",
        "",
        "| area | used | total | used % |",
        "| --- | ---: | ---: | ---: |",
    ]
    if isinstance(areas, list):
        for area in areas:
            if not isinstance(area, dict):
                continue
            lines.append(
                f"| `{area.get('area', '')}` | {area.get('used', 0)}"
                f" | {area.get('total', 0)} | {area.get('used_pct', 0)} |"
            )
    return lines + [""]


def _coverage_table(coverage: Any) -> list[str]:
    lines = [
        "## Coverage",
        "",
        "| surface | measured | active | torn | dropped | unknown | incomplete |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    if isinstance(coverage, list):
        for item in coverage:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"| `{item.get('surface', '')}` | {item.get('measured_days', 0)}"
                f" | {item.get('active_days', 0)} | {item.get('torn', 0)}"
                f" | {item.get('dropped', 0)} | {item.get('unknown_ids', 0)}"
                f" | {item.get('incomplete_days', 0)} |"
            )
    return lines + [""]


def _row_table(rows: Any, header: dict[str, Any]) -> list[str]:
    lines = [
        "## Features",
        "",
        "| id | state | days | last used | uses | decision |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            uses = row.get("uses", {})
            uses_text = (
                ", ".join(f"{name} {count}" for name, count in sorted(uses.items()))
                if isinstance(uses, dict) and uses
                else "—"
            )
            decision = row.get("decision") or "—"
            lines.append(
                f"| `{row.get('id', '')}` | {row.get('state', '')}"
                f" | {row.get('days_used', 0)} | {row.get('last_used_day') or '—'}"
                f" | {uses_text} | {decision} |"
            )
            lines.append("")
            lines.append(f"> {evidence_sentence(row, header)}")
            lines.append("")
    return lines


def card_markdown(card: dict[str, Any], header: dict[str, Any]) -> str:
    """Return the evidence card as agent-ready Markdown."""
    row = dict(card.get("row", {}))
    lines = [f"# `{row.get('id', '')}`", ""]
    lines.append(
        f"{row.get('label', '')} · {row.get('area', '')} · {row.get('kind', '')}"
    )
    lines.append("")
    lines.append(evidence_sentence(card, header))
    lines.append("")
    uses = row.get("uses", {})
    if isinstance(uses, dict) and uses:
        lines.append(
            "Uses: "
            + ", ".join(f"{name} {count}" for name, count in sorted(uses.items()))
        )
    via = row.get("via", {})
    if isinstance(via, dict) and via:
        lines.append(
            "Via: "
            + ", ".join(f"{name} {count}" for name, count in sorted(via.items()))
        )
    outcome = row.get("outcome", {})
    if isinstance(outcome, dict) and outcome:
        lines.append(
            "Outcome: "
            + ", ".join(f"{name} {count}" for name, count in sorted(outcome.items()))
        )
    if row.get("loc") is not None:
        lines.append(f"LOC: {row.get('loc')}")
    siblings = card.get("retire_with", [])
    if isinstance(siblings, list) and siblings:
        lines.append("Siblings: " + ", ".join(f"`{item}`" for item in siblings))
    children = card.get("children", [])
    if isinstance(children, list) and children:
        lines.append("Children: " + ", ".join(f"`{item}`" for item in children))
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def review_markdown(report: dict[str, Any]) -> str:
    """Render every locally decided feature as agent-ready review Markdown."""
    header = dict(report.get("header", {}))
    rows = report.get("rows", [])
    selected = (
        [
            dict(row)
            for row in rows
            if isinstance(row, dict) and row.get("decision") in {"keep", "later", "cut"}
        ]
        if isinstance(rows, list)
        else []
    )
    selected.sort(key=lambda row: str(row.get("id", "")))

    lines = ["# Footprint review decisions", ""]
    lines.append(
        f"Window {header.get('window_start', '—')} → "
        f"{header.get('window_end', '—')} · actor everyone"
    )
    counts = dict.fromkeys(("keep", "later", "cut"), 0)
    for row in selected:
        decision = row.get("decision")
        if decision in counts:
            counts[decision] += 1
    lines.append(
        f"Marked: {counts['keep']} keep · {counts['later']} later · {counts['cut']} cut"
    )
    lines.append("")
    for row in selected:
        feature_id = str(row.get("id", ""))
        decision = str(row.get("decision", ""))
        lines.append(f"## `{feature_id}` — {row.get('label', feature_id)}")
        lines.append("")
        lines.append(
            f"Decision: **{decision}** · area `{row.get('area', '—')}` · "
            f"kind `{row.get('kind', '—')}` · state `{row.get('state', '—')}`"
        )
        reason = row.get("decision_reason")
        if decision == "keep" and isinstance(reason, str) and reason:
            lines.append(f"Keep reason: `{reason}`")
        uses = row.get("uses", {})
        if isinstance(uses, dict):
            lines.append(
                "Uses: "
                + ", ".join(
                    f"{actor} {uses.get(actor, 0)}"
                    for actor in ("human", "agent", "automation")
                )
            )
        lines.append(
            f"Observed active days: {row.get('days_used', 0)} · "
            f"last used: {row.get('last_used_day') or '—'} · "
            f"carrying cost: {row.get('loc') if row.get('loc') is not None else 'unknown'} LOC"
        )
        lines.append("")
        lines.append(f"> {evidence_sentence(row, header)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["card_markdown", "report_markdown", "review_markdown"]
