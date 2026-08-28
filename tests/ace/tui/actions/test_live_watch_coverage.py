"""Roster-driven live inotify coverage after an agents load."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading_apply import AgentLoadingApplyMixin
from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyBoundary,
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedFoldFiltering,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_runner_slots import RunnerCapacitySnapshot


class _FakeWatcher:
    def __init__(self) -> None:
        self.ensure_calls: list[list[Path]] = []
        self.prune_calls: list[list[Path]] = []

    def ensure_watches(self, paths: Any) -> int:
        installed = [Path(path) for path in paths]
        self.ensure_calls.append(installed)
        return len(installed)

    def prune_agent_dir_watches(self, paths: Any) -> int:
        pruned = [Path(path) for path in paths]
        self.prune_calls.append(pruned)
        return len(pruned)


class _ApplyHarness(AgentLoadingApplyMixin):
    def __init__(self, watcher: _FakeWatcher | None) -> None:
        self.current_tab = "patches"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._has_always_visible = False
        self._hidden_count = 0
        self._hideable_agents: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._revived_agent_raw_suffixes: set[str] = set()
        self._agents_first_load_done = True
        self._agents_seen_complete_history = False
        self._agents_history_reconcile_pending = False
        self._agents_history_reconcile_armed_mono = 0.0
        self._agent_load_state = None
        self._agents_index_repair_notice_key = None
        self._agent_search_query = ""
        self._agent_query_cache = None
        self._agent_status_overrides: dict[object, object] = {}
        self._agents_refresh_active_source = "test"
        self._agents_repro_capture = None
        self._fs_watcher = watcher
        self.finalize_calls = 0

    def _finalize_agent_list(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.finalize_calls += 1

    def _schedule_artifact_index_maintenance(self, **kwargs: object) -> None:
        del kwargs

    def _schedule_live_hint_refresh(self, *, source: str = "unknown") -> None:
        del source

    def _schedule_bead_confirmation_warmup(self, *, source: str = "unknown") -> None:
        del source

    def _schedule_diff_badge_classification(self, *, source: str = "unknown") -> None:
        del source


def _agent(
    cl_name: str,
    raw_suffix: str,
    artifacts_dir: Path,
    *,
    status: str,
    start_time: datetime | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=start_time or datetime(2026, 8, 28, 14, 0, 0),
        raw_suffix=raw_suffix,
        artifacts_dir=str(artifacts_dir),
    )


def _apply(app: _ApplyHarness, agents: list[Agent]) -> None:
    prep = PreparedApplyData(
        filtered_agents=list(agents),
        has_always_visible=False,
        hidden_count=0,
        hideable_agents=list(agents),
        dismissed_agent_objects=[],
    )
    boundary = PreparedApplyBoundary(
        prep=prep,
        fold=PreparedFoldFiltering(
            unfiltered_agents=list(agents),
            visible_agents=list(agents),
            fold_counts={},
        ),
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
        runner_capacity=RunnerCapacitySnapshot(),
        finalize=None,
    )
    app._apply_loaded_agents_prepared_inner(
        prep,
        on_agents_tab=False,
        selected_identity=None,
        persist_dismissed_changes=False,
        incomplete_merge_already_applied=True,
        precomputed_boundary=boundary,
        precomputed_fold_levels=None,
    )


def test_apply_ensures_watch_for_in_flight_dir_created_before_watcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_dir = tmp_path / "20260828135111"
    live_dir.mkdir()
    monkeypatch.setattr(
        "sase.ace.tui.models.artifact_files.get_artifacts_dir",
        lambda agent: agent.artifacts_dir,
    )
    watcher = _FakeWatcher()
    app = _ApplyHarness(watcher)
    live = _agent("0fn--code", live_dir.name, live_dir, status="RUNNING")

    _apply(app, [live])

    assert watcher.ensure_calls == [[live_dir]]
    assert watcher.prune_calls == []


def test_apply_prunes_watch_when_loaded_row_is_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done_dir = tmp_path / "20260828140403"
    done_dir.mkdir()
    monkeypatch.setattr(
        "sase.ace.tui.models.artifact_files.get_artifacts_dir",
        lambda agent: agent.artifacts_dir,
    )
    watcher = _FakeWatcher()
    app = _ApplyHarness(watcher)
    done = _agent("0fn--code", done_dir.name, done_dir, status="DONE")

    _apply(app, [done])

    assert watcher.ensure_calls == []
    assert watcher.prune_calls == [[done_dir]]


def test_apply_skips_watch_coverage_without_fs_watcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_dir = tmp_path / "20260828135111"
    live_dir.mkdir()
    monkeypatch.setattr(
        "sase.ace.tui.models.artifact_files.get_artifacts_dir",
        lambda agent: agent.artifacts_dir,
    )
    app = _ApplyHarness(None)
    live = _agent("0fn--code", live_dir.name, live_dir, status="RUNNING")

    _apply(app, [live])

    assert app._agents_with_children == [live]


def test_apply_caps_live_watches_newest_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._live_watch_coverage.MAX_LIVE_AGENT_WATCHES",
        1,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.artifact_files.get_artifacts_dir",
        lambda agent: agent.artifacts_dir,
    )
    older_dir = tmp_path / "20260828120000"
    newer_dir = tmp_path / "20260828140403"
    older_dir.mkdir()
    newer_dir.mkdir()
    watcher = _FakeWatcher()
    app = _ApplyHarness(watcher)
    older = _agent(
        "older",
        older_dir.name,
        older_dir,
        status="RUNNING",
        start_time=datetime(2026, 8, 28, 12, 0, 0),
    )
    newer = _agent(
        "newer",
        newer_dir.name,
        newer_dir,
        status="RUNNING",
        start_time=datetime(2026, 8, 28, 14, 4, 3),
    )

    _apply(app, [older, newer])

    assert watcher.ensure_calls == [[newer_dir]]
