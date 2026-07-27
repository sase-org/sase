"""Output-variable sections for agent browsing pages."""

from __future__ import annotations

from sase.agents_sync.rendering_markdown import (
    md_cell,
    md_code,
    relative_page_url,
)
from sase.agents_sync.v2_models import V2RunRecord

_DISPLAY_VALUE_LIMIT = 200


def output_variables(run: V2RunRecord) -> tuple[tuple[str, str], ...]:
    """Return one run's validated output variables in display order."""

    raw = dict(run.metadata).get("output_variables")
    if not isinstance(raw, dict):
        return ()
    return tuple(
        sorted(
            (key, value)
            for key, value in raw.items()
            if isinstance(key, str) and isinstance(value, str)
        )
    )


def render_agent_variables(run: V2RunRecord, *, source_path: str) -> list[str]:
    """Render an agent's output-variable section."""

    variables = output_variables(run)
    if not variables:
        return []
    lines = [
        "## Variables",
        "",
        "| Variable | Value |",
        "|---|---|",
    ]
    truncated = False
    for key, value in variables:
        display, was_truncated = _display_value(value)
        truncated = truncated or was_truncated
        lines.append(f"| `{md_code(key)}` | {md_cell(display)} |")
    lines.append("")
    if truncated:
        refs = dict(run.files)
        meta_path = (
            refs["meta"].path
            if "meta" in refs
            else source_path.rsplit("/", 1)[0] + "/meta.json"
        )
        lines.extend(
            [
                "Values are truncated for display; see "
                f"[meta.json]({relative_page_url(source_path, meta_path)}) "
                "for the full values.",
                "",
            ]
        )
    return lines


def render_family_variables(
    members: tuple[tuple[str, V2RunRecord], ...],
) -> list[str]:
    """Render attributed output variables for a family."""

    rows = sorted(
        (
            (role, key, value, run.source_run_id)
            for role, run in members
            for key, value in output_variables(run)
        ),
        key=lambda row: (row[0], row[1], row[3]),
    )
    if not rows:
        return []
    lines = [
        "## Variables",
        "",
        "| Role | Variable | Value |",
        "|---|---|---|",
    ]
    truncated = False
    for role, key, value, _run_id in rows:
        display, was_truncated = _display_value(value)
        truncated = truncated or was_truncated
        lines.append(f"| {md_cell(role)} | `{md_code(key)}` | {md_cell(display)} |")
    lines.append("")
    if truncated:
        lines.extend(
            [
                "Values are truncated for display; see each member's "
                "agent meta.json for the full values.",
                "",
            ]
        )
    return lines


def _display_value(value: str) -> tuple[str, bool]:
    if len(value) <= _DISPLAY_VALUE_LIMIT:
        return value, False
    return value[:_DISPLAY_VALUE_LIMIT] + "…", True


__all__ = [
    "output_variables",
    "render_agent_variables",
    "render_family_variables",
]
