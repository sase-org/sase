"""Flat OptionList construction and row rendering for the Agent pane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from rich.text import Text
from textual.widgets.option_list import Option

from sase.agents.catalog import AgentCatalogRow
from sase.agents.status_style import agent_status_text

from .agents_data import AgentsSnapshot
from .entry_navigation import ArtifactEntryTarget, prepend_jump_hint, prepend_mark_glyph

AGENTS_PANE_ID = "agents"

_NAME_WIDTH = 28
_KIND_WIDTH = 8
_PROJECT_WIDTH = 16


@dataclass(frozen=True, slots=True)
class AgentRow:
    """Identity-preserving row backing one selectable agent option."""

    option_id: str
    entry: AgentCatalogRow


def agent_row_target(row: AgentRow) -> ArtifactEntryTarget:
    """Use the registry name as the stable navigation identity."""

    return ArtifactEntryTarget(pane_id=AGENTS_PANE_ID, parts=(row.entry.name,))


def _agent_row_text(entry: AgentCatalogRow) -> Text:
    """Render one aligned, single-line agent catalog row."""

    kind = "/".join(entry.kind) if entry.kind else "-"
    project = entry.project or "-"
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f"{entry.name}".ljust(_NAME_WIDTH), style="bold white")
    text.append(f"{kind}".ljust(_KIND_WIDTH), style="#87D7FF")
    if entry.status:
        text.append_text(agent_status_text(entry.status.upper()))
        text.append(" ")
    else:
        text.append("- ", style="dim")
    text.append(f"[{project}]".ljust(_PROJECT_WIDTH), style="dim")
    if entry.revivable:
        text.append("↺ revivable", style="bold #5FD7AF")
    elif not entry.from_artifact_index and not entry.from_dismissed_archive:
        text.append("no run data", style="dim")
    return text


def build_agent_options(
    snapshot: AgentsSnapshot | None,
    *,
    loading: bool,
    jump_hints: Mapping[ArtifactEntryTarget, str] | None = None,
    marks: set[ArtifactEntryTarget] | None = None,
) -> tuple[list[Option], dict[str, AgentRow]]:
    """Build the flat, ungrouped option list for the current snapshot."""

    active_marks = marks or set()
    hints = jump_hints or {}
    if snapshot is None:
        label = "Loading agents…" if loading else "Agents have not loaded yet."
        return [Option(label, disabled=True)], {}
    if not snapshot.rows:
        return [], {}
    options: list[Option] = []
    rows: dict[str, AgentRow] = {}
    for entry in snapshot.rows:
        option_id = f"agent:{entry.name}"
        row = AgentRow(option_id, entry)
        rows[option_id] = row
        target = agent_row_target(row)
        options.append(
            Option(
                prepend_jump_hint(
                    prepend_mark_glyph(
                        _agent_row_text(entry),
                        target in active_marks,
                    ),
                    hints.get(target),
                ),
                id=option_id,
            )
        )
    return options, rows


__all__ = [
    "AGENTS_PANE_ID",
    "AgentRow",
    "agent_row_target",
    "build_agent_options",
]
