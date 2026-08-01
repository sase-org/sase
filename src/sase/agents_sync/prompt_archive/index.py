"""Deterministic generated month indexes for archived prompts."""

from __future__ import annotations

from pathlib import Path

from sase.sdd.plan_header_block import (
    PlanHeaderSectionKind,
    parse_plan_header_block,
)


def render_prompt_month_index(month_dir: Path) -> str:
    """Render the stable README table for one prompt month."""

    rows: list[tuple[str, str, str, str, int]] = []
    for path in sorted(month_dir.glob("*.md"), key=lambda item: item.name):
        if path.name == "README.md":
            continue
        parsed = parse_plan_header_block(path.read_text(encoding="utf-8"))
        plan = next(
            (s for s in parsed.sections if s.kind is PlanHeaderSectionKind.PLAN),
            None,
        )
        agents = next(
            (s for s in parsed.sections if s.kind is PlanHeaderSectionKind.AGENTS),
            None,
        )
        artifacts = next(
            (s for s in parsed.sections if s.kind is PlanHeaderSectionKind.ARTIFACTS),
            None,
        )
        rows.append(
            (
                path.name,
                _document_title(parsed.body, path.stem),
                _section_link(plan.label, plan.target) if plan is not None else "-",
                _section_link(
                    agents.entries[0].label,
                    agents.entries[0].target,
                )
                if agents is not None and agents.entries
                else "-",
                len(artifacts.entries) if artifacts is not None else 0,
            )
        )
    lines = [
        f"# Prompt archive: {month_dir.name}",
        "",
        "| Prompt | Title | Plan | Agent | Artifacts |",
        "| --- | --- | --- | --- | ---: |",
    ]
    lines.extend(
        f"| [{name}]({name}) | {_escape(title)} | {plan} | {agent} | {count} |"
        for name, title, plan, agent, count in rows
    )
    lines.append("")
    return "\n".join(lines)


def _document_title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return fallback


def _section_link(label: str | None, target: str | None) -> str:
    if not label:
        return "-"
    safe_label = _escape(label)
    return f"[{safe_label}]({target})" if target else safe_label


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


__all__ = ["render_prompt_month_index"]
