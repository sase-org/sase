"""Lifecycle and race tests for Agents-tab fold-state persistence."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._fold_persistence import AgentFoldPersistenceMixin
from sase.ace.tui.actions.agents._fold_scope import reconcile_panel_fold_registries
from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.models.agent_fold_persistence import (
    AgentGroupingFoldSnapshot,
    AgentsFoldStateSnapshot,
    load_agents_fold_state,
    save_agents_fold_state,
)
from sase.ace.tui.models.agent_group_fold import (
    AgentGroupFoldRegistry,
    AgentPanelFoldScope,
    AgentPanelFoldSnapshot,
)
from sase.ace.tui.models.agent_groups import GroupingMode


class _Harness(AgentFoldingMixin, AgentFoldPersistenceMixin):
    def __init__(self, *, first_load_done: bool = False) -> None:
        self._grouping_mode = GroupingMode.STANDARD
        self._group_fold_registries = {self._grouping_mode: AgentGroupFoldRegistry()}
        self._group_fold_registry = self._group_fold_registries[self._grouping_mode]
        self._collapsed_panel_keys: set[str | None] = set()
        self._panel_group = SimpleNamespace(focused_key=None, panel_keys=[None])
        self._agent_panels_grouped = False
        self._current_group_key: tuple[str, ...] | None = None
        self._agents_first_load_done = first_load_done
        self.refilter_calls: list[dict[str, Any]] = []
        self._ensure_agents_fold_persistence_state()

    def _refilter_agents(self, **kwargs: Any) -> None:
        self.refilter_calls.append(kwargs)

    def _invalidate_agent_panel_cache(self) -> None:
        return


def _baseline() -> AgentsFoldStateSnapshot:
    return AgentsFoldStateSnapshot(
        collapsed_panels=frozenset({"persisted"}),
        group_folds=(
            AgentGroupingFoldSnapshot(
                GroupingMode.BY_STATUS,
                (
                    AgentPanelFoldSnapshot(
                        AgentPanelFoldScope(None),
                        frozenset({("Done",)}),
                    ),
                    AgentPanelFoldSnapshot(
                        AgentPanelFoldScope("research"),
                        frozenset({("Done",)}),
                    ),
                ),
            ),
        ),
    )


def test_load_race_installs_baseline_then_replays_newer_user_intent() -> None:
    app = _Harness()
    app._record_agents_group_fold_change(("sase",), collapsed=True)
    app._record_agents_panel_fold_change("chop", collapsed=True)

    app._resolve_agents_fold_state_load(_baseline())

    assert app.refilter_calls == []
    assert app._maybe_install_agents_fold_state_before_finalize() is True
    assert (
        app._group_fold_registries[GroupingMode.BY_STATUS]
        .for_panel(None)
        .is_collapsed(("Done",))
    )
    assert (
        app._group_fold_registries[GroupingMode.BY_STATUS]
        .for_panel("research")
        .is_collapsed(("Done",))
    )
    assert app._group_fold_registry.for_panel(None).is_collapsed(("sase",))
    assert app._collapsed_panel_keys == {"persisted", "chop"}
    assert app._agents_fold_state_intents == []


def test_collapse_then_expand_journal_persists_expanded_result() -> None:
    app = _Harness()
    app._record_agents_group_fold_change(("Done",), collapsed=True)
    app._record_agents_group_fold_change(("Done",), collapsed=False)
    app._record_agents_panel_fold_change("chop", collapsed=True)
    app._record_agents_panel_fold_change("chop", collapsed=False)

    app._resolve_agents_fold_state_load(_baseline())
    app._maybe_install_agents_fold_state_before_finalize()

    assert not app._group_fold_registry.for_panel(None).is_collapsed(("Done",))
    assert "chop" not in app._collapsed_panel_keys
    assert "persisted" in app._collapsed_panel_keys


def test_panel_expansion_helper_wins_when_persisted_load_is_still_in_flight() -> None:
    app = _Harness()
    app._panel_group = SimpleNamespace(focused_key="chop", panel_keys=["chop"])
    app._collapsed_panel_keys.add("chop")

    assert app._expand_agent_panel("chop") is True
    assert app._collapsed_panel_keys == set()

    app._resolve_agents_fold_state_load(
        AgentsFoldStateSnapshot(collapsed_panels=frozenset({"chop"}))
    )
    app._maybe_install_agents_fold_state_before_finalize()

    assert app._collapsed_panel_keys == set()


def test_merged_layout_clear_removes_unseen_persisted_panel_folds() -> None:
    app = _Harness()
    app._record_agents_panel_folds_cleared()

    app._resolve_agents_fold_state_load(_baseline())
    app._maybe_install_agents_fold_state_before_finalize()

    assert app._collapsed_panel_keys == set()
    assert (
        app._group_fold_registries[GroupingMode.BY_STATUS]
        .for_panel(None)
        .is_collapsed(("Done",))
    )


def test_stale_group_and_panel_pruning_enqueues_clean_snapshot() -> None:
    app = _Harness()
    app._agents_fold_state_merged = True
    app._collapsed_panel_keys.add("vanished")
    app._group_fold_registry.for_panel("vanished").collapse(("Done",))

    reconcile_panel_fold_registries(
        app,
        {AgentPanelFoldScope(None): []},
    )

    assert app._collapsed_panel_keys == set()
    assert AgentPanelFoldScope("vanished") not in app._group_fold_registry._registries
    pending = app._agents_fold_state_save_pending
    assert pending is not None
    generation, snapshot = pending
    assert generation == 1
    assert snapshot.collapsed_panels == frozenset()
    assert snapshot.group_folds == ()


def test_late_load_uses_in_memory_full_rebuild_refresh() -> None:
    app = _Harness(first_load_done=True)

    app._resolve_agents_fold_state_load(_baseline())

    assert app._agents_fold_state_merged is True
    assert app.refilter_calls == [{"previous_agents": []}]


def test_done_and_chop_survive_a_fresh_session(tmp_path: Path) -> None:
    first = _Harness()
    first._grouping_mode = GroupingMode.BY_STATUS
    first._group_fold_registries = {GroupingMode.BY_STATUS: AgentGroupFoldRegistry()}
    first._group_fold_registry = first._group_fold_registries[GroupingMode.BY_STATUS]
    first._group_fold_registry.for_panel(None).collapse(("Done",))
    first._collapsed_panel_keys.add("chop")
    snapshot = first._capture_agents_fold_state()
    path = tmp_path / "folds.json"
    save_agents_fold_state(snapshot, path)

    fresh = _Harness()
    fresh._grouping_mode = GroupingMode.BY_STATUS
    fresh._resolve_agents_fold_state_load(load_agents_fold_state(path))
    fresh._maybe_install_agents_fold_state_before_finalize()

    assert fresh._group_fold_registry.for_panel(None).is_collapsed(("Done",))
    assert fresh._collapsed_panel_keys == {"chop"}


@pytest.mark.asyncio
async def test_rapid_mutations_coalesce_to_latest_generation() -> None:
    app = _Harness()
    app._agents_fold_state_merged = True
    started = threading.Event()
    release = threading.Event()
    saved: list[AgentsFoldStateSnapshot] = []

    def _save(snapshot: AgentsFoldStateSnapshot) -> None:
        saved.append(snapshot)
        if len(saved) == 1:
            started.set()
            release.wait(timeout=2)

    app._save_agents_fold_state_now = _save  # type: ignore[method-assign]
    registry = app._group_fold_registry.for_panel(None)
    registry.collapse(("Done",))
    app._agents_fold_state_changed()
    assert await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=0.5)

    registry.expand(("Done",))
    app._agents_fold_state_changed()
    release.set()
    while app._agents_fold_state_completed_generation < 2:
        await asyncio.sleep(0)

    assert len(saved) == 2
    assert saved[0].group_folds
    assert saved[-1].group_folds == ()


@pytest.mark.asyncio
async def test_flush_waits_for_latest_queued_generation() -> None:
    app = _Harness()
    app._agents_fold_state_merged = True
    started = threading.Event()
    release = threading.Event()

    def _save(_snapshot: AgentsFoldStateSnapshot) -> None:
        started.set()
        release.wait(timeout=2)

    app._save_agents_fold_state_now = _save  # type: ignore[method-assign]
    app._collapsed_panel_keys.add("chop")
    app._agents_fold_state_changed()
    assert await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=0.5)

    flush = asyncio.create_task(app._flush_agents_fold_state())
    await asyncio.sleep(0)
    assert not flush.done()
    release.set()
    await asyncio.wait_for(flush, timeout=0.5)
    assert app._agents_fold_state_completed_generation == 1
