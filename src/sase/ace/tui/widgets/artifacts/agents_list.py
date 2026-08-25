"""OptionList construction, grouping, and row rendering for the Agent pane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from rich.text import Text
from textual.widgets.option_list import Option

from sase.agents.catalog import AgentCatalogRow
from sase.agents.status_style import agent_status_text

from ..._artifact_tab_model import PaneGroupingModeDecl
from ...models.artifact_groups import ArtifactGroupBuildResult, build_grouped_rows
from ...models.group_fold import GroupFoldRegistry
from .agents_data import AgentsSnapshot
from .entry_navigation import ArtifactEntryTarget, prepend_jump_hint, prepend_mark_glyph
from .group_banner import format_group_banner_option

AGENTS_PANE_ID = "agents"

_NAME_WIDTH = 28
_KIND_WIDTH = 8
_PROJECT_WIDTH = 16

#: Sentinel bucket key for rows a grouping mode has no real value for
#: (no family/clan membership, no recorded state, no project). Sorts first
#: so ungrouped rows anchor at the top rather than scattering alphabetically.
_UNGROUPED = "!ungrouped"


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


def _agent_key_value(entry: AgentCatalogRow, mode_id: str) -> str:
    if mode_id == "by_family":
        if entry.family:
            return entry.family
        if "family" in entry.kind:
            return entry.name
        return _UNGROUPED
    if mode_id == "by_state":
        return entry.state or _UNGROUPED
    if mode_id == "by_project":
        return entry.project or _UNGROUPED
    return ""


def _agent_group_label(mode_id: str, value: str) -> str:
    if value == _UNGROUPED:
        if mode_id == "by_family":
            return "(no family)"
        if mode_id == "by_state":
            return "(no state)"
        return "(no project)"
    if mode_id == "by_state":
        return value.title()
    return value


def build_grouped_agent_rows(
    snapshot: AgentsSnapshot,
    *,
    mode: PaneGroupingModeDecl,
    fold_registry: GroupFoldRegistry | None = None,
) -> ArtifactGroupBuildResult[AgentCatalogRow]:
    """Bucket already-loaded, newest-first agent rows by the active mode."""

    return build_grouped_rows(
        snapshot.rows,
        pane_id=AGENTS_PANE_ID,
        mode_id=mode.id,
        keys=(mode.id,),
        key_values=lambda entry: (_agent_key_value(entry, mode.id),),
        label_for=lambda _level, value: _agent_group_label(mode.id, value),
        target_for=lambda entry: ArtifactEntryTarget(
            pane_id=AGENTS_PANE_ID, parts=(entry.name,)
        ),
        fold_registry=fold_registry,
    )


def build_agent_options(
    snapshot: AgentsSnapshot | None,
    *,
    loading: bool,
    mode: PaneGroupingModeDecl | None = None,
    fold_registry: GroupFoldRegistry | None = None,
    accent: str = "#87D7FF",
    jump_hints: Mapping[ArtifactEntryTarget, str] | None = None,
    marks: set[ArtifactEntryTarget] | None = None,
) -> tuple[list[Option], dict[str, AgentRow], tuple[tuple[str, ...], ...]]:
    """Build the current snapshot's option list, grouped when *mode* is set.

    Returns ``(options, rows, known_group_keys)``.
    """

    active_marks = marks or set()
    hints = jump_hints or {}
    if snapshot is None:
        label = "Loading agents…" if loading else "Agents have not loaded yet."
        return [Option(label, disabled=True)], {}, ()
    if not snapshot.rows:
        return [], {}, ()

    def _row_option(entry: AgentCatalogRow) -> tuple[str, AgentRow, Option]:
        option_id = f"agent:{entry.name}"
        row = AgentRow(option_id, entry)
        target = agent_row_target(row)
        option = Option(
            prepend_jump_hint(
                prepend_mark_glyph(
                    _agent_row_text(entry),
                    target in active_marks,
                ),
                hints.get(target),
            ),
            id=option_id,
        )
        return option_id, row, option

    if mode is None:
        options: list[Option] = []
        rows: dict[str, AgentRow] = {}
        for entry in snapshot.rows:
            option_id, row, option = _row_option(entry)
            rows[option_id] = row
            options.append(option)
        return options, rows, ()

    result = build_grouped_agent_rows(snapshot, mode=mode, fold_registry=fold_registry)
    options = []
    rows = {}
    for grouped_row in result.rows:
        if grouped_row.kind == "banner" and grouped_row.banner is not None:
            banner = grouped_row.banner
            options.append(
                format_group_banner_option(
                    banner,
                    accent=accent,
                    hint_char=hints.get(banner.target),
                )
            )
            continue
        grouped_entry = grouped_row.item
        assert grouped_entry is not None
        option_id, row, option = _row_option(grouped_entry)
        rows[option_id] = row
        options.append(option)
    return options, rows, result.known_group_keys


__all__ = [
    "AGENTS_PANE_ID",
    "AgentRow",
    "agent_row_target",
    "build_agent_options",
    "build_grouped_agent_rows",
]
