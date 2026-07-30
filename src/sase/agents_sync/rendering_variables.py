"""Output-variable sections for agent browsing pages."""

from __future__ import annotations

import re

from sase.agents_sync.rendering_markdown import (
    md_cell,
    md_code,
    relative_page_url,
)
from sase.agents_sync.v2_models import V2RunRecord
from sase.core.output_variable_display import (
    format_var_value_block,
    format_var_value_inline,
    var_value_is_container,
)
from sase.core.output_variable_values import (
    MAX_OUTPUT_VARIABLE_ENCODED_BYTES,
    VarValue,
    coerce_var_map,
)

_DISPLAY_VALUE_LIMIT = 200
_DISPLAY_BLOCK_LINE_LIMIT = 200
_DISPLAY_BLOCK_BYTE_LIMIT = 16 * 1024


def output_variables(run: V2RunRecord) -> tuple[tuple[str, VarValue], ...]:
    """Return one run's validated output variables in display order."""

    raw = dict(run.metadata).get("output_variables")
    return tuple(coerce_var_map(raw).items())


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
    for key, value in variables:
        if not var_value_is_container(value):
            continue
        block, was_truncated = _display_block(value)
        truncated = truncated or was_truncated
        lines.extend(
            [
                f"#### {key}",
                "",
                f"{_block_fence(block)}yaml",
                block,
                _block_fence(block),
                "",
            ]
        )
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
    for role, key, value, _run_id in rows:
        if not var_value_is_container(value):
            continue
        block, was_truncated = _display_block(value)
        truncated = truncated or was_truncated
        lines.extend(
            [
                f"#### {key}",
                "",
                f"**Role:** `{md_code(role)}`",
                "",
                f"{_block_fence(block)}yaml",
                block,
                _block_fence(block),
                "",
            ]
        )
    if truncated:
        lines.extend(
            [
                "Values are truncated for display; see each member's "
                "agent meta.json for the full values.",
                "",
            ]
        )
    return lines


def _display_value(value: VarValue) -> tuple[str, bool]:
    display = format_var_value_inline(value, max_chars=_DISPLAY_VALUE_LIMIT)
    unbounded = format_var_value_inline(
        value,
        max_chars=MAX_OUTPUT_VARIABLE_ENCODED_BYTES * 8,
    )
    return display, len(unbounded) > _DISPLAY_VALUE_LIMIT


def _display_block(value: VarValue) -> tuple[str, bool]:
    block, line_truncated = format_var_value_block(
        value,
        max_lines=_DISPLAY_BLOCK_LINE_LIMIT - 1,
    )
    if line_truncated:
        block = f"{block}\n…" if block else "…"
    byte_truncated = len(block.encode("utf-8")) > _DISPLAY_BLOCK_BYTE_LIMIT
    if byte_truncated:
        suffix = "…".encode()
        block = (
            block.encode("utf-8")[: _DISPLAY_BLOCK_BYTE_LIMIT - len(suffix)]
            .decode("utf-8", errors="ignore")
            .rstrip()
            + "…"
        )
    return block, line_truncated or byte_truncated


def _block_fence(block: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", block)), default=0)
    return "`" * max(3, longest + 1)


__all__ = [
    "output_variables",
    "render_agent_variables",
    "render_family_variables",
]
