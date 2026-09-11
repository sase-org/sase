"""Shared helpers for agents-tab incomplete merge tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    merge_incomplete_load_after_complete_history,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_loader import AgentLoadState


def _incomplete_tier1_snapshot(
    cached_agents_with_children: Sequence[Agent],
    *,
    artifact_source: str = "artifact_index",
    used_artifact_index: bool = True,
    load_state: AgentLoadState | None = None,
    capacity_agents_with_children: Sequence[Agent] = (),
    deleted_artifact_dirs: frozenset[str] = frozenset(),
) -> PreparedApplySnapshot:
    if load_state is None:
        load_state = AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source=artifact_source,
            used_artifact_index=used_artifact_index,
            deleted_artifact_dirs=deleted_artifact_dirs,
        )

    return PreparedApplySnapshot(
        cached_agents_with_children=list(cached_agents_with_children),
        dismissed_agents=set(),
        agents_seen_complete_history=True,
        hide_non_run_agents=False,
        load_state=load_state,
        fold_levels=None,
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
        capacity_agents_with_children=list(capacity_agents_with_children),
    )


def _merge_tier1_patch(cached: list[Agent], incoming: list[Agent]) -> list[Agent]:
    prep = PreparedApplyData(
        filtered_agents=incoming,
        has_always_visible=bool(incoming),
        hidden_count=0,
        hideable_agents=list(incoming),
        dismissed_agent_objects=[],
    )
    snapshot = _incomplete_tier1_snapshot(cached)

    merge_incomplete_load_after_complete_history(prep, snapshot)
    return prep.filtered_agents


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
