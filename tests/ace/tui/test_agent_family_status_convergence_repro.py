"""Regression repros for family-shell status convergence after settlement."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._loading_apply import AgentLoadingApplyMixin
from sase.ace.tui.actions.agents._loading_compute import (
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.actions.agents._notification_utils import (
    request_notification_agents_refresh,
)
from sase.ace.tui.actions.event_refresh._auto_refresh import EventAutoRefreshMixin
from sase.ace.tui.actions.event_refresh._surface_tokens import probe_surface_tokens
from sase.ace.tui.data_providers import AgentsViewport
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.bead.epic_launch_handoff import (
    CompletionNotificationPayload,
    defer_epic_completion_until_monitor_settlement,
    publish_deferred_monitor_completion,
)
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
    upsert_agent_artifact_index_row,
)
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.notifications import Notification, load_notifications

from ._event_handlers_dirty_flags_helpers import _FakeApp

_ROOT_TS = "20260915130000"
_GATE_TS = "20260915130300"
_MONITOR_TS = "20260915130530"


@dataclass(frozen=True)
class _IncidentTree:
    projects_root: Path
    project_dir: Path
    root_dir: Path
    gate_dir: Path
    monitor_dir: Path


class _PreparedApplyHarness(AgentLoadingApplyMixin):
    """Small app stand-in that drives the production prepared-apply path."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_capacity_with_children: list[Agent] = []
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._has_always_visible = False
        self._hidden_count = 0
        self._hideable_agents: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._revived_agent_raw_suffixes: set[str] = set()
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_search_query = ""
        self._agent_query_cache = None
        self._agent_panels_grouped = False
        self._agents_first_load_done = True
        self._agents_seen_complete_history = False
        self._agents_complete_history_query_key = None
        self._agents_history_reconcile_pending = False
        self._agents_history_reconcile_armed_mono = 0.0
        self._agent_load_state: AgentLoadState | None = None
        self._agents_index_repair_notice_key = None
        self._agents_refresh_active_source = "test"
        self._agents_repro_capture = None
        self._artifact_index_schema_rebuild_in_flight = False
        self._fs_watcher = None
        self._last_completed_surface_tokens: dict[str, object] = {}
        self.finalize_calls = 0
        self.notices: list[tuple[str, str | None]] = []
        self.live_hint_refresh_sources: list[str] = []

    def query_one(self, selector: str, _widget_type: object) -> Any:
        raise LookupError(selector)

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notices.append((message, severity))

    def _finalize_agent_list(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.finalize_calls += 1

    def _schedule_artifact_index_maintenance(self, **kwargs: object) -> None:
        del kwargs

    def _schedule_live_hint_refresh(self, *, source: str = "unknown") -> None:
        self.live_hint_refresh_sources.append(source)

    def _schedule_bead_confirmation_warmup(self, *, source: str = "unknown") -> None:
        del source

    def _schedule_diff_badge_classification(self, *, source: str = "unknown") -> None:
        del source


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _build_incident_tree(sase_home: Path) -> _IncidentTree:
    projects_root = sase_home / "projects"
    project_dir = projects_root / "home"
    project_dir.mkdir(parents=True)
    (project_dir / "home.sase").write_text("NAME: home\n", encoding="utf-8")
    root_dir = project_dir / "artifacts" / "ace-run" / _ROOT_TS
    gate_dir = project_dir / "artifacts" / "ace-run" / _GATE_TS
    monitor_dir = project_dir / "artifacts" / "ace-run" / _MONITOR_TS

    _write_json(
        root_dir / "workflow_state.json",
        {
            "workflow_name": "ace-run",
            "context": {"cl_name": "0l4"},
            "status": "running",
            "appears_as_agent": True,
            "start_time": "2026-09-15T13:00:00",
            "steps": [],
        },
    )
    _write_json(
        root_dir / "agent_meta.json",
        {
            "name": "0l4",
            "cl_name": "0l4",
            "agent_family": "0l4",
            "agent_family_role": "root",
            "plan_chain_root": True,
            "role_suffix": "--plan",
            "plan": True,
            "plan_approved": True,
            "plan_action": "epic",
            "run_started_at": "2026-09-15T13:00:00Z",
        },
    )
    _write_json(
        gate_dir / "workflow_state.json",
        {
            "workflow_name": "ace-run",
            "context": {"cl_name": "0l4--gate"},
            "status": "running",
            "appears_as_agent": True,
            "start_time": "2026-09-15T13:03:00",
            "steps": [],
        },
    )
    _write_json(
        gate_dir / "agent_meta.json",
        {
            "name": "0l4--gate",
            "cl_name": "0l4--gate",
            "agent_family": "0l4",
            "agent_family_role": "gate",
            "role_suffix": "--gate",
            "parent_timestamp": _ROOT_TS,
            "run_started_at": "2026-09-15T13:03:00Z",
            "gate_id": "gate-1",
            "gate_state": "settling",
            "gate_start_status": "EPIC APPROVED",
            "gate_stop_status": "EPIC APPROVED",
        },
    )
    _write_json(
        monitor_dir / "workflow_state.json",
        {
            "workflow_name": "ace-run",
            "context": {"cl_name": "0l4--mon"},
            "status": "running",
            "appears_as_agent": True,
            "start_time": "2026-09-15T13:05:30",
            "steps": [],
        },
    )
    _write_json(
        monitor_dir / "agent_meta.json",
        {
            "name": "0l4--mon",
            "cl_name": "0l4--mon",
            "agent_family": "0l4",
            "agent_family_role": "monitor",
            "role_suffix": "--mon",
            "parent_timestamp": _GATE_TS,
            "run_started_at": "2026-09-15T13:05:30Z",
            "monitor_id": "mon-1",
            "monitor_state": "running",
            "monitor_start_status": "EPIC APPROVED",
            "monitor_stop_status": "EPIC CREATED",
            "monitor_command": "sase bead work sase-117",
            "monitor_settled": False,
        },
    )
    for index in range(10):
        sibling_dir = project_dir / "artifacts" / "ace-run" / f"2026091512{index:02d}00"
        _write_json(
            sibling_dir / "agent_meta.json",
            {
                "name": f"sibling-{index}",
                "stopped_at": "2026-09-15T12:59:00Z",
            },
        )
        _write_json(
            sibling_dir / "done.json",
            {
                "outcome": "completed",
                "cl_name": f"sibling-{index}",
                "name": f"sibling-{index}",
            },
        )
    return _IncidentTree(
        projects_root=projects_root,
        project_dir=project_dir,
        root_dir=root_dir,
        gate_dir=gate_dir,
        monitor_dir=monitor_dir,
    )


def _settle_monitor(tree: _IncidentTree) -> None:
    _write_json(
        tree.monitor_dir / "agent_meta.json",
        {
            "name": "0l4--mon",
            "cl_name": "0l4--mon",
            "agent_family": "0l4",
            "agent_family_role": "monitor",
            "role_suffix": "--mon",
            "parent_timestamp": _GATE_TS,
            "run_started_at": "2026-09-15T13:05:30Z",
            "stopped_at": "2026-09-15T13:05:31Z",
            "monitor_id": "mon-1",
            "monitor_state": "completed",
            "monitor_start_status": "EPIC APPROVED",
            "monitor_stop_status": "EPIC CREATED",
            "monitor_command": "sase bead work sase-117",
            "monitor_settled": True,
            "monitor_exit_code": 0,
        },
    )
    _write_json(
        tree.monitor_dir / "done.json",
        {
            "outcome": "monitored",
            "cl_name": "0l4--mon",
            "name": "0l4--mon",
            "status_label": "EPIC CREATED",
            "finished_at": 1789477531.0,
            "monitor_id": "mon-1",
            "monitor_state": "completed",
            "monitor_start_status": "EPIC APPROVED",
            "monitor_stop_status": "EPIC CREATED",
            "monitor_exit_code": 0,
        },
    )
    (tree.project_dir / "artifacts" / ".ace_refresh_pulse").write_text(
        "settled\n",
        encoding="utf-8",
    )


def _defer_production_completion(tree: _IncidentTree) -> None:
    payload = CompletionNotificationPayload(
        sender="user-agent",
        cl_name="0l4",
        success=True,
        notes=["planner completed"],
        action="JumpToAgent",
        action_data={
            "cl_name": "0l4",
            "raw_suffix": _ROOT_TS,
        },
        extra_files=[],
        silent=False,
        tags=["done"],
    )
    assert defer_epic_completion_until_monitor_settlement(
        tree.root_dir,
        tree.monitor_dir,
        payload,
    )


def _publish_production_completion(tree: _IncidentTree) -> Notification:
    assert publish_deferred_monitor_completion(
        tree.monitor_dir,
        outcome={"status": "success"},
    )
    notifications = load_notifications()
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.sender == "user-agent"
    assert notification.action == "JumpToAgent"
    assert notification.tags == ["done"]
    assert notification.action_data["cl_name"] == "0l4--mon"
    assert notification.action_data["raw_suffix"] == _MONITOR_TS
    assert notification.action_data["family_root_suffix"] == _ROOT_TS
    assert notification.action_data["agent_root_timestamp"] == _ROOT_TS
    return notification


def _load_bounded_agents(source: str) -> Any:
    from sase.ace.tui.actions.agents._loading_helpers import (
        load_agents_from_disk_with_state,
    )

    return load_agents_from_disk_with_state(
        set(),
        patch_snapshot=[],
        viewport=AgentsViewport(start_row=0, visible_rows=2, prefetch_rows=2),
        source=source,
    )


def _load_exact_delta(source: str, artifact_dirs: list[Path]) -> Any:
    from sase.ace.tui.actions.agents._loading_helpers import (
        load_agent_artifact_delta_from_disk_with_state,
    )

    return load_agent_artifact_delta_from_disk_with_state(
        set(),
        artifact_dirs,
        patch_snapshot=[],
        source=source,
        update_index=False,
    )


def _apply_result(
    app: _PreparedApplyHarness,
    result: Any,
    *,
    source: str,
) -> None:
    selected_identity = app._agents[app.current_idx].identity if app._agents else None
    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=True,
        selected_identity=selected_identity,
        load_state=result.load_state,
    )
    boundary = prepare_loaded_agents_worker_boundary(
        result.all_agents,
        result.dismissed_from_loader,
        set(app._dismissed_agents),
        bool(app.hide_non_run_agents),
        snapshot,
        dismissed_bundle_snapshot=set(
            getattr(result, "dismissed_bundle_identities", set())
        ),
    )
    previous_source = app._agents_refresh_active_source
    app._agents_refresh_active_source = source
    try:
        app._apply_loaded_agents_prepared(
            boundary.prep,
            on_agents_tab=True,
            selected_identity=selected_identity,
            load_state=result.load_state,
            persist_dismissed_changes=False,
            incomplete_merge_already_applied=True,
            precomputed_boundary=boundary,
            precomputed_fold_levels=snapshot.fold_levels,
        )
    finally:
        app._agents_refresh_active_source = previous_source


def _concrete_rows(app: _PreparedApplyHarness) -> list[Agent]:
    return [
        agent
        for agent in app._agents_with_children
        if not getattr(agent, "is_clan_container", False)
    ]


def _statuses_for_suffix(app: _PreparedApplyHarness, suffix: str) -> tuple[str, ...]:
    return tuple(
        agent.status for agent in _concrete_rows(app) if agent.raw_suffix == suffix
    )


def _load_state_is_bounded(load_state: AgentLoadState) -> bool:
    return (
        load_state.tier == "tier1"
        and load_state.artifact_source == "artifact_index"
        and load_state.bounded_prefix
        and load_state.has_more
    )


def test_enqueue_agent_artifact_delta_paths_keeps_exact_dirs_under_fallback(
    tmp_path: Path,
) -> None:
    """A fallback flag must not make later exact marker writes unrecoverable."""
    app = _FakeApp(watcher_active=True, sdd_beads_dir=tmp_path / "sdd" / "beads")
    marker = (
        tmp_path
        / ".sase"
        / "projects"
        / "home"
        / "artifacts"
        / "ace-run"
        / _MONITOR_TS
        / "done.json"
    )
    _write_json(marker, {"outcome": "monitored", "status_label": "EPIC CREATED"})

    app._dirty_agent_artifact_fallback_reason = "unknown_watcher_path"
    app._enqueue_agent_artifact_delta_paths((marker,))

    assert app._dirty_agent_artifact_fallback_reason == "unknown_watcher_path"
    assert app._dirty_agent_artifact_dirs == (marker.parent,)


@pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for the artifact-index incident replay",
)
def test_settlement_notification_exact_delta_converges_before_index_upsert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production completion notification refreshes the family chain exactly."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    tree = _build_incident_tree(sase_home)
    rebuild_agent_artifact_index(
        default_agent_artifact_index_path(),
        tree.projects_root,
        AgentArtifactScanOptionsWire(),
    )

    app = _PreparedApplyHarness()
    scheduled: list[tuple[Path, ...]] = []
    app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
        lambda dirs, *, source: scheduled.append(tuple(dirs))
    )

    with patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}):
        initial = _load_bounded_agents("startup")
        _apply_result(app, initial, source="startup")
        assert _statuses_for_suffix(app, _ROOT_TS) == ("EPIC APPROVED",)
        assert _statuses_for_suffix(app, _MONITOR_TS) == ("EPIC APPROVED",)

        _defer_production_completion(tree)
        assert load_notifications() == []
        _settle_monitor(tree)
        assert (tree.monitor_dir / "done.json").exists()
        monitor_meta = json.loads(
            (tree.monitor_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert monitor_meta["monitor_settled"] is True
        notification = _publish_production_completion(tree)
        request_notification_agents_refresh(app, notifications=[notification])

        assert scheduled == [(tree.monitor_dir, tree.gate_dir, tree.root_dir)]
        notification_delta = _load_exact_delta("notification", list(scheduled[0]))
        _apply_result(app, notification_delta, source="notification")
        assert _statuses_for_suffix(app, _ROOT_TS) == ("EPIC CREATED",)
        assert _statuses_for_suffix(app, _MONITOR_TS) == ("EPIC CREATED",)


@pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for the artifact-index incident replay",
)
def test_settled_monitor_replay_converges_after_index_upsert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay the stale-family incident through loader, merge, apply, and tokens."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    tree = _build_incident_tree(sase_home)
    rebuild_agent_artifact_index(
        default_agent_artifact_index_path(),
        tree.projects_root,
        AgentArtifactScanOptionsWire(),
    )

    app = _PreparedApplyHarness()
    failures: list[str] = []
    with patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}):
        initial = _load_bounded_agents("startup")
        _apply_result(app, initial, source="startup")
        initial_tokens = probe_surface_tokens()
        EventAutoRefreshMixin._accept_surface_token(app, "agents", initial_tokens)

        if not _load_state_is_bounded(initial.load_state):
            failures.append(
                f"step 1 expected bounded Tier-1 load, got {initial.load_state}"
            )
        if _statuses_for_suffix(app, _ROOT_TS) != ("EPIC APPROVED",):
            failures.append(
                f"step 1 root should mirror running monitor, got "
                f"{_statuses_for_suffix(app, _ROOT_TS)!r}"
            )
        if _statuses_for_suffix(app, _MONITOR_TS) != ("EPIC APPROVED",):
            failures.append(
                f"step 1 monitor should be running, got "
                f"{_statuses_for_suffix(app, _MONITOR_TS)!r}"
            )

        _settle_monitor(tree)
        settlement_tokens = probe_surface_tokens()
        if not EventAutoRefreshMixin._surface_token_drifted(
            app,
            settlement_tokens,
            "agents",
        ):
            failures.append("step 2 settlement pulse should dirty the agents token")

        notification = _load_bounded_agents("notification")
        _apply_result(app, notification, source="notification")
        EventAutoRefreshMixin._accept_surface_token(app, "agents", settlement_tokens)
        if not _load_state_is_bounded(notification.load_state):
            failures.append(
                f"step 3 expected stale bounded notification load, got "
                f"{notification.load_state}"
            )
        if _statuses_for_suffix(app, _ROOT_TS) != ("EPIC APPROVED",):
            failures.append(
                f"step 3 stale index should leave root pre-settlement, got "
                f"{_statuses_for_suffix(app, _ROOT_TS)!r}"
            )
        if _statuses_for_suffix(app, _MONITOR_TS) != ("EPIC APPROVED",):
            failures.append(
                f"step 3 stale index should leave monitor pre-settlement, got "
                f"{_statuses_for_suffix(app, _MONITOR_TS)!r}"
            )

        watcher_delta = _load_exact_delta(
            "watcher",
            [tree.root_dir, tree.gate_dir],
        )
        _apply_result(app, watcher_delta, source="watcher")
        EventAutoRefreshMixin._accept_surface_token(app, "agents", settlement_tokens)
        if _statuses_for_suffix(app, _ROOT_TS) != ("EPIC APPROVED",):
            failures.append(
                f"step 4 monitor-missing delta should leave root stale, got "
                f"{_statuses_for_suffix(app, _ROOT_TS)!r}"
            )
        if _statuses_for_suffix(app, _MONITOR_TS) != ("EPIC APPROVED",):
            failures.append(
                f"step 4 monitor-missing delta should leave monitor stale, got "
                f"{_statuses_for_suffix(app, _MONITOR_TS)!r}"
            )

        upsert_agent_artifact_index_row(
            default_agent_artifact_index_path(),
            tree.projects_root,
            tree.monitor_dir,
            AgentArtifactScanOptionsWire(),
        )
        after_upsert_tokens = probe_surface_tokens()
        if not EventAutoRefreshMixin._surface_token_drifted(
            app,
            after_upsert_tokens,
            "agents",
        ):
            failures.append(
                "step 5 accepted the agents token before any load covered the settled "
                "monitor dir"
            )

        post_upsert = _load_bounded_agents("auto_refresh")
        _apply_result(app, post_upsert, source="auto_refresh")
        if _statuses_for_suffix(app, _ROOT_TS) != ("EPIC CREATED",):
            failures.append(
                f"step 6 first post-upsert load should converge root, got "
                f"{_statuses_for_suffix(app, _ROOT_TS)!r}"
            )
        if _statuses_for_suffix(app, _MONITOR_TS) != ("EPIC CREATED",):
            failures.append(
                f"step 6 first post-upsert load should converge monitor, got "
                f"{_statuses_for_suffix(app, _MONITOR_TS)!r}"
            )

    assert failures == []
