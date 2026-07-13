"""Agent-specific WORKSPACES context section helpers for the prompt panel."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text

from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent

from ._agent_context_common import (
    COLOR_EXTERNAL_REPO_GLYPH,
    COLOR_EXTERNAL_REPO_NAME,
    COLOR_EMPTY,
    COLOR_TRUNCATION,
    COLOR_WORKSPACE_GLYPH,
    COLOR_WORKSPACE_NAME,
    COLOR_WORKSPACE_PATH,
    COLOR_WORKSPACE_SUBHEADER,
    EXTERNAL_REPO_GLYPH,
    WORKSPACE_GLYPH,
    WORKSPACE_PATH_CONNECTOR,
    append_context_lane_header,
    append_context_reason,
    append_lane_row,
    count_phrase,
    format_local_hhmm,
    normalize_context_display,
    truncate_display,
)

MAX_VISIBLE_OPENED_WORKSPACES = 5
WORKSPACE_NAME_LIMIT = 48
WORKSPACE_PATH_LIMIT = 64


def _workspace_path_display(workspace_dir: str) -> str:
    display = normalize_context_display(workspace_dir)
    if len(display) <= WORKSPACE_PATH_LIMIT:
        return display
    name = Path(display).name
    compact = f"…/{name}" if name else "…"
    return truncate_display(compact, WORKSPACE_PATH_LIMIT)


def append_agent_opened_workspaces_section(
    text: Text,
    *,
    events: tuple[OpenedWorkspaceDisplayEvent, ...] = (),
    show_empty: bool = False,
) -> None:
    """Append a WORKSPACES sub-section listing opened linked workspaces."""
    if not events:
        if show_empty:
            append_context_lane_header(
                text,
                "WORKSPACES",
                label_style=COLOR_WORKSPACE_SUBHEADER,
                details="none recorded",
                details_style=COLOR_EMPTY,
            )
        return

    distinct_repos = len({item.name for item in events})
    distinct_agents = len({item.agent_label for item in events if item.agent_label})
    details = (
        f"{count_phrase(len(events), 'open')} · {count_phrase(distinct_repos, 'repo')}"
    )
    if distinct_agents > 1:
        details += f" · {count_phrase(distinct_agents, 'agent')}"
    append_context_lane_header(
        text,
        "WORKSPACES",
        label_style=COLOR_WORKSPACE_SUBHEADER,
        details=details,
    )

    visible = events[:MAX_VISIBLE_OPENED_WORKSPACES]
    show_role_column = any(item.agent_label for item in visible)
    for event in visible:
        external = event.kind == "external"
        reason_indent = append_lane_row(
            text,
            timestamp=event.opened_at,
            glyph=EXTERNAL_REPO_GLYPH if external else WORKSPACE_GLYPH,
            glyph_style=(
                COLOR_EXTERNAL_REPO_GLYPH if external else COLOR_WORKSPACE_GLYPH
            ),
            primary=truncate_display(event.name, WORKSPACE_NAME_LIMIT),
            primary_style=(
                COLOR_EXTERNAL_REPO_NAME if external else COLOR_WORKSPACE_NAME
            ),
            role_label=event.agent_label,
            show_role_column=show_role_column,
        )
        path_display = _workspace_path_display(event.workspace_dir)
        if path_display:
            text.append(
                f"  {WORKSPACE_PATH_CONNECTOR} {path_display}",
                style=COLOR_WORKSPACE_PATH,
            )
        text.append("\n")
        append_context_reason(text, event.reason, indent=reason_indent)

    overflow = len(events) - len(visible)
    if overflow > 0:
        earliest = events[-1]
        text.append(
            f"  + {overflow} more · {format_local_hhmm(earliest.opened_at)} earliest\n",
            style=COLOR_TRUNCATION,
        )
