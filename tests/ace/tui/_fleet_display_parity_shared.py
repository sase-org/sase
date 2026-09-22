"""Shared parity constants and render-comparison helpers.

Split out of ``test_fleet_agents_display_parity.py`` so the display-parity
tests can live in focused files without duplicating the comparison logic.
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._display_panel_titles import (
    agent_panel_border_title,
    agent_panel_counts,
)
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_panels import agents_for_panel, panel_keys_for
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets._agent_list_helpers import compute_fold_annotation
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.core.time import local_now

_PARITY_TZ = local_now().tzinfo
_PARITY_NOW = datetime(2026, 9, 13, 12, 10, tzinfo=_PARITY_TZ)
_PARITY_STARTED_AT = 1_789_300_800.0
_PARITY_PROJECT_FILE = "/tmp/sase-main/project.yml"
_PARITY_REMOTE_ALIAS = "apollo"
_PARITY_INTENT = "prove display parity"


def _at(unix: float) -> datetime:
    return datetime.fromtimestamp(unix, tz=_PARITY_TZ)


def _rendered_rows(rows: list[Agent]) -> list[str]:
    return [
        format_agent_option(
            row,
            index,
            is_selected=False,
            now=_PARITY_NOW,
            show_machine_chip=True,
        )[0].plain
        for index, row in enumerate(rows)
    ]


def _normalized_rendered_rows(rows: list[Agent]) -> list[str]:
    return [_without_remote_host_chip(text) for text in _rendered_rows(rows)]


def _normalized_collapsed_render(rows: list[Agent]) -> list[str]:
    visible, fold_counts = filter_agents_by_fold_state(rows, FoldStateManager())
    rendered = [
        format_agent_option(
            row,
            index,
            is_selected=False,
            fold_annotation=compute_fold_annotation(row, fold_counts, set()),
            now=_PARITY_NOW,
            show_machine_chip=True,
        )[0].plain
        for index, row in enumerate(visible)
    ]
    return [_without_remote_host_chip(text) for text in rendered]


def _without_remote_host_chip(text: str) -> str:
    return text.replace(f"{_PARITY_REMOTE_ALIAS} ", "")


def _tree_signature(rows: list[Agent]) -> list[tuple[object, ...]]:
    row_by_raw = {row.raw_suffix: _row_key(row) for row in rows if row.raw_suffix}
    row_by_fold = {
        fold_key: _row_key(row)
        for row in rows
        if (fold_key := agent_fold_key(row)) is not None
    }

    def parent_key(row: Agent) -> object:
        key = row.tree_parent_key or row.parent_timestamp
        if key is None:
            return None
        return row_by_fold.get(key) or row_by_raw.get(key)

    return [
        (
            _row_key(row),
            parent_key(row),
            row.status,
            row.is_clan_container,
            row.is_family_container_row,
            row.is_monitor,
            row.is_gate,
            row.is_proc_shell,
            tuple(_row_key(child) for child in row.followup_agents),
            tuple(_row_key(child) for child in row.runtime_children),
        )
        for row in rows
    ]


def _row_key(row: Agent) -> tuple[object, ...]:
    if row.is_clan_container:
        return ("clan", row.agent_clan, row.agent_clan_generation)
    return (
        "row",
        row.agent_name,
        row.agent_family_role,
        row.agent_clan,
        row.agent_clan_generation,
    )


def _visible_node_count(rows: list[Agent]) -> int:
    visible, _fold_counts = filter_agents_by_fold_state(rows, FoldStateManager())
    return len(visible)


def _panel_signature(rows: list[Agent]) -> list[tuple[object, ...]]:
    signature: list[tuple[object, ...]] = []
    for key in panel_keys_for(rows):
        slice_rows = agents_for_panel(rows, key)
        counts = agent_panel_counts(slice_rows, set())
        title = agent_panel_border_title(key, counts.lane_count, counts=counts)
        signature.append(
            (
                key,
                counts.lane_count,
                counts.running,
                counts.waiting,
                counts.read,
                counts.failed,
                title.plain,
            )
        )
    return signature
