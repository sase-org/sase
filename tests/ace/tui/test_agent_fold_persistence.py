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
from sase.ace.tui.models.agent_panels import PanelIsolationRevert


class _Harness(AgentFoldingMixin, AgentFoldPersistenceMixin):
    def __init__(self, *, first_load_done: bool = False) -> None:
        self._grouping_mode = GroupingMode.STANDARD
        self._group_fold_registries = {self._grouping_mode: AgentGroupFoldRegistry()}
        self._group_fold_registry = self._group_fold_registries[self._grouping_mode]
        self._collapsed_panel_keys: set[str | None] = set()
        self._expanded_panel_keys: set[str | None] = set()
        self._panel_isolation_revert: PanelIsolationRevert | None = None
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
    assert app._collapsed_panel_keys == set()
    assert app._expanded_panel_keys == set()
    assert app._agents_fold_state_intents == []


def test_collapse_then_expand_journal_persists_group_result() -> None:
    app = _Harness()
    app._record_agents_group_fold_change(("Done",), collapsed=True)
    app._record_agents_group_fold_change(("Done",), collapsed=False)

    app._resolve_agents_fold_state_load(_baseline())
    app._maybe_install_agents_fold_state_before_finalize()

    assert not app._group_fold_registry.for_panel(None).is_collapsed(("Done",))
    assert app._collapsed_panel_keys == set()
    assert app._expanded_panel_keys == set()


def test_panel_expansion_helper_wins_when_persisted_load_is_still_in_flight() -> None:
    app = _Harness()
    app._panel_group = SimpleNamespace(focused_key="chop", panel_keys=["chop"])
    app._collapsed_panel_keys.add("chop")

    assert app._expand_agent_panel("chop") is True
    assert app._collapsed_panel_keys == set()
    assert app._expanded_panel_keys == {"chop"}

    app._resolve_agents_fold_state_load(AgentsFoldStateSnapshot())
    app._maybe_install_agents_fold_state_before_finalize()

    assert app._collapsed_panel_keys == set()
    assert app._expanded_panel_keys == {"chop"}


def test_panel_intent_recorded_before_late_load_survives_install() -> None:
    app = _Harness()
    app._collapsed_panel_keys.add("chop")

    app._resolve_agents_fold_state_load(_baseline())
    app._maybe_install_agents_fold_state_before_finalize()

    assert app._collapsed_panel_keys == {"chop"}
    assert app._expanded_panel_keys == set()
    assert (
        app._group_fold_registries[GroupingMode.BY_STATUS]
        .for_panel(None)
        .is_collapsed(("Done",))
    )


def test_partial_projection_preserves_panel_intent_and_prunes_stale_groups() -> None:
    app = _Harness()
    app._agents_fold_state_merged = True
    app._collapsed_panel_keys.add("vanished")
    app._expanded_panel_keys.add("also-vanished")
    app._group_fold_registry.for_panel("vanished").collapse(("Done",))

    reconcile_panel_fold_registries(
        app,
        {AgentPanelFoldScope(None): []},
    )

    assert app._collapsed_panel_keys == {"vanished"}
    assert app._expanded_panel_keys == {"also-vanished"}
    assert AgentPanelFoldScope("vanished") not in app._group_fold_registry._registries
    pending = app._agents_fold_state_save_pending
    assert pending is not None
    generation, snapshot = pending
    assert generation == 1
    assert not hasattr(snapshot, "collapsed_panels")
    assert not hasattr(snapshot, "expanded_panels")
    assert snapshot.group_folds == ()


def test_legacy_panel_state_is_ignored_at_startup_and_config_applies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "folds.json"
    path.write_text(
        """
        {
          "schema_version": 3,
          "expanded_panels": [{"kind": "tribe", "tribe": "chop"}],
          "group_folds": [
            {
              "mode": "by_status",
              "scopes": [
                {
                  "panel": {"kind": "no_tribe"},
                  "merged": false,
                  "collapsed": [["Done"]]
                }
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    fresh = _Harness()
    fresh._resolve_agents_fold_state_load(load_agents_fold_state(path))
    fresh._maybe_install_agents_fold_state_before_finalize()

    from sase.ace.tui.actions.agents._panel_fold_intent import (
        effective_panel_collapses,
    )
    from sase.ace.tui.models import tribe_display

    monkeypatch.setattr(
        tribe_display,
        "tribe_display_for",
        lambda key: SimpleNamespace(initially_expanded=key != "chop"),
    )
    assert fresh._collapsed_panel_keys == set()
    assert fresh._expanded_panel_keys == set()
    assert effective_panel_collapses(fresh, {"chop"}) == {"chop"}
    assert (
        fresh._group_fold_registries[GroupingMode.BY_STATUS]
        .for_panel(None)
        .is_collapsed(("Done",))
    )


def test_late_load_uses_in_memory_full_rebuild_refresh() -> None:
    app = _Harness(first_load_done=True)

    app._resolve_agents_fold_state_load(_baseline())

    assert app._agents_fold_state_merged is True
    assert app.refilter_calls == [{"previous_agents": []}]


def test_fold_state_install_disarms_panel_isolation_restore() -> None:
    app = _Harness()
    app._panel_isolation_revert = PanelIsolationRevert(
        target_key=None,
        collapsed_before=frozenset(),
    )

    app._resolve_agents_fold_state_load(_baseline())
    app._maybe_install_agents_fold_state_before_finalize()

    assert app._panel_isolation_revert is None


def test_group_folds_survive_a_fresh_session_but_panel_intent_does_not(
    tmp_path: Path,
) -> None:
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
    assert fresh._collapsed_panel_keys == set()
    assert fresh._expanded_panel_keys == set()


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
