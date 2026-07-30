"""Agent-specific XPROMPTS metadata helpers for the prompt panel header."""

from __future__ import annotations

from typing import Any

from rich.text import Text

from ._agent_context_common import count_phrase, truncate_display

_COLOR_HEADER = "bold #87D7FF"
_COLOR_SUMMARY = "dim"
_COLOR_WORKFLOW = "bold #FFAF5F"
_COLOR_PART = "bold #87FFAF"
_COLOR_SWARM = "bold #FF87D7"
_COLOR_ARGS = "dim"
_WORKFLOW_GLYPH = "⌘"
_PART_GLYPH = "▣"
_SWARM_GLYPH = "❋"
_ARG_VALUE_LIMIT = 40


def append_agent_xprompts_section(
    text: Text,
    xprompts_used: list[dict[str, Any]] | None,
    *,
    project_key: str | None = None,
    project_display_name: str | None = None,
) -> None:
    """Append the selected agent's xprompt reference summary when available."""
    xprompts = xprompts_used or []
    if not xprompts:
        return

    text.append("Xprompts: ", style=_COLOR_HEADER)
    text.append(_summary(xprompts), style=_COLOR_SUMMARY)
    text.append("\n")

    for item in xprompts:
        kind = item.get("kind")
        if kind == "workflow":
            glyph = _WORKFLOW_GLYPH
            style = _COLOR_WORKFLOW
        elif kind == "swarm":
            glyph = _SWARM_GLYPH
            style = _COLOR_SWARM
        else:
            glyph = _PART_GLYPH
            style = _COLOR_PART

        name = str(item.get("name") or "unknown")
        text.append(f"  {glyph} ", style=style)
        text.append(f"#{name}", style=style)

        args_display = _format_args(
            item,
            project_key=project_key,
            project_display_name=project_display_name,
        )
        if args_display:
            text.append("  ")
            text.append(args_display, style=_COLOR_ARGS)
        text.append("\n")


def _summary(xprompts: list[dict[str, Any]]) -> str:
    swarm_count = sum(1 for item in xprompts if item.get("kind") == "swarm")
    workflow_count = sum(1 for item in xprompts if item.get("kind") == "workflow")
    part_count = sum(1 for item in xprompts if item.get("kind") == "part")
    parts: list[str] = []
    if swarm_count:
        parts.append(count_phrase(swarm_count, "swarm"))
    if workflow_count:
        parts.append(count_phrase(workflow_count, "workflow"))
    if part_count:
        parts.append(count_phrase(part_count, "part"))
    return " · ".join(parts) if parts else count_phrase(len(xprompts), "xprompt")


def _format_args(
    item: dict[str, Any],
    *,
    project_key: str | None = None,
    project_display_name: str | None = None,
) -> str:
    positional = item.get("positional")
    named = item.get("named")
    pieces: list[str] = []

    if isinstance(positional, list):
        pieces.extend(
            _truncate_value(
                _display_arg_value(
                    value,
                    project_key=project_key,
                    project_display_name=project_display_name,
                )
            )
            for value in positional
        )
    if isinstance(named, dict):
        pieces.extend(
            _format_named_arg(
                key,
                value,
                project_key=project_key,
                project_display_name=project_display_name,
            )
            for key, value in named.items()
        )

    return ", ".join(piece for piece in pieces if piece)


def _format_named_arg(
    key: Any,
    value: Any,
    *,
    project_key: str | None,
    project_display_name: str | None,
) -> str:
    display_value = _display_arg_value(
        value,
        project_key=project_key,
        project_display_name=project_display_name,
    )
    return f"{key}={_truncate_value(display_value)}"


def _display_arg_value(
    value: Any,
    *,
    project_key: str | None,
    project_display_name: str | None,
) -> Any:
    if (
        project_key
        and project_display_name
        and isinstance(value, str)
        and value == project_key
    ):
        return project_display_name
    return value


def _truncate_value(value: Any) -> str:
    return truncate_display(str(value), _ARG_VALUE_LIMIT)
