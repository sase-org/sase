"""Agent Hijack submission overlays and ledger presentation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._hijack_action import AgentHijackActionMixin
from sase.ace.tui.actions.agents._kill_action_flow import AgentKillActionFlowMixin
from sase.ace.tui.models._agent_status_apply import _mirror_root_from_child
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_hijack_presentation import (
    HIJACK_PENDING_TRACKER,
    _HijackPendingTracker,
    apply_hijack_ledger_presentation,
    pending_hijack_status_text,
)
from sase.agent.hijack.referral import _RemoteHijackReferral
from tests.ace.tui._agent_hijack_action_helpers import (
    make_hijack_agent,
    make_hijack_view,
    make_latched_record,
)


def test_hijack_submission_shows_pending_and_stop_failed_rows(
    monkeypatch: Any,
) -> None:
    agent = make_hijack_agent()
    callbacks: list[Any] = []
    notifications: list[tuple[str, str]] = []

    class App(AgentHijackActionMixin):
        _agents_with_children = [agent]

        def notify(self, message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

        def _refresh_agents_display(
            self, *, list_changed: bool, defer_detail: bool
        ) -> None:
            del list_changed, defer_detail

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._roster_generation.notify_roster_status_mutation",
        lambda _app: None,
    )

    submitted_names: list[str] = []

    def submit(_app: object, **kwargs: Any) -> bool:
        submitted_names.append(kwargs["name"])
        callbacks.append(kwargs["on_complete"])
        return True

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_durable.submit_agent_hijack", submit
    )
    app._store_hijack_decision(agent, make_hijack_view(agent, mode="immediate"))

    assert app._start_hijack_agent(agent)
    assert agent.hijack_overlay == "hijacking"
    assert submitted_names == ["sase-demo.1"]

    callbacks[0](
        SimpleNamespace(
            payload={"status": "stop_failed", "severity": "error"},
            message="Surviving process 421",
            success=False,
        )
    )

    assert agent.hijack_overlay is None
    assert agent.hijack_stop_failed is True
    assert notifications == [("Surviving process 421", "error")]


def test_active_ledger_records_drive_hijack_overlays_and_summary(
    tmp_path: Any, monkeypatch: Any
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    agent = make_hijack_agent(status="HIJACKED")
    agent.artifacts_dir = str(artifacts_dir)
    records = [
        {
            "hijack_id": "h-held",
            "artifacts_dir": str(artifacts_dir),
            "revision": 3,
            "state": "held",
            "repo_diffs": [
                {"files_changed": 3, "insertions": 8, "deletions": 2},
                {"files_changed": 2, "insertions": 4, "deletions": 1},
            ],
        }
    ]
    monkeypatch.setattr("sase.agent.hijack.ledger.list_active_records", lambda: records)

    apply_hijack_ledger_presentation([agent])

    assert agent.hijack_overlay is None
    assert agent.hijack_diff_summary == "5 files +12 −3"
    assert agent.hijack_record == records[0]

    records[0]["state"] = "resolving"
    apply_hijack_ledger_presentation([agent])

    assert agent.hijack_overlay == "recovering"
    assert agent.hijack_diff_summary is None

    records[0]["state"] = "stopping"
    apply_hijack_ledger_presentation([agent])

    assert agent.hijack_overlay == "hijacking"


def test_remote_referral_overlay_is_projected_from_the_store(
    monkeypatch: Any,
) -> None:
    agent = make_hijack_agent()
    agent.fleet_origin_alias = "athena"
    monkeypatch.setattr(
        "sase.agent.hijack.ledger.list_active_records",
        lambda: [],
    )
    monkeypatch.setattr(
        "sase.agent.hijack.referral._list_active_remote_hijack_referrals",
        lambda **_kwargs: [
            _RemoteHijackReferral(
                alias="athena",
                agent="sase-demo.1",
                requested_at=1.0,
                ttl_seconds=7200.0,
            )
        ],
    )

    apply_hijack_ledger_presentation([agent])

    assert agent.hijack_overlay == "referred"


def test_settled_hijack_record_is_loaded_by_done_marker_id(
    monkeypatch: Any,
) -> None:
    agent = make_hijack_agent(status="HIJACKED")
    agent.hijack_id = "h-expired"
    record = {
        "hijack_id": "h-expired",
        "artifacts_dir": "/tmp/agent-artifacts",
        "revision": 7,
        "state": "expired",
    }
    monkeypatch.setattr("sase.agent.hijack.ledger.list_active_records", lambda: [])
    monkeypatch.setattr(
        "sase.agent.hijack.ledger.load_record", lambda hijack_id: record
    )

    apply_hijack_ledger_presentation([agent])

    assert agent.hijack_record == record


def test_x_on_hijacked_agent_submits_durable_dismiss(
    monkeypatch: Any,
) -> None:
    agent = make_hijack_agent(status="HIJACKED")
    agent.hijack_id = "h-123"
    agent.hijack_record = {
        "hijack_id": "h-123",
        "agent_name": agent.agent_name,
        "revision": 4,
        "state": "held",
    }
    dismissed: list[Agent] = []

    class App(AgentKillActionFlowMixin):
        current_tab = "agents"
        _marked_agents: set[Any] = set()
        _current_group_key = None
        _agents_with_children = [agent]

        def _get_selected_agent(self) -> Agent:
            return agent

        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._archive_actions.guard_archive_live_action",
        lambda _app, _action: False,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._hijack_recovery_panel.dismiss_hijacked_agent",
        lambda _app, row: dismissed.append(row) or True,
    )

    app.action_kill_agent()

    assert dismissed == [agent]


def test_collapsed_session_mirrors_hijack_record() -> None:
    parent = make_hijack_agent()
    parent.agent_type = AgentType.WORKFLOW
    parent.agent_name = "tailnet-t.10"
    parent.agent_session_role = "root"
    child = make_hijack_agent(status="HIJACKED")
    child.agent_name = "tailnet-t.10--1"
    child.hijack_id = "h-held"
    child.hijack_record = {"hijack_id": "h-held", "state": "held"}
    child.hijack_diff_summary = "2 files +4 −1"
    child.hijack_expired = False

    _mirror_root_from_child(parent, child)

    assert parent.status == "HIJACKED"
    assert parent.hijack_record == child.hijack_record
    assert parent.hijack_id == "h-held"
    assert parent.hijack_diff_summary == "2 files +4 −1"


def test_latched_ledger_record_projects_pending_overlay_on_member_and_container(
    tmp_path: Any, monkeypatch: Any
) -> None:
    HIJACK_PENDING_TRACKER.reset()
    try:
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        parent = make_hijack_agent()
        parent.agent_name = "session-root"
        parent.agent_session = "session-root"
        parent.agent_session_role = "root"
        child = make_hijack_agent()
        child.agent_name = "session-root--1"
        child.agent_session = "session-root"
        child.artifacts_dir = str(artifacts_dir)
        parent.followup_agents = [child]
        records = [
            make_latched_record(
                artifacts_dir=str(artifacts_dir),
                agent_name=child.agent_name,
                boundary="retry",
            )
        ]
        monkeypatch.setattr(
            "sase.agent.hijack.ledger.list_active_records", lambda: records
        )

        apply_hijack_ledger_presentation([parent, child])

        assert child.hijack_overlay == "pending"
        assert child.hijack_record == records[0]
        assert child.hijack_id == "h-latched"
        assert parent.hijack_overlay == "pending"
        assert parent.hijack_record == records[0]
        assert pending_hijack_status_text(child.hijack_record) == (
            "⏏ HIJACK PENDING · after retry"
        )

        apply_hijack_ledger_presentation([parent, child])
        assert child.hijack_overlay == "pending"
        assert parent.hijack_overlay == "pending"
    finally:
        HIJACK_PENDING_TRACKER.reset()


def test_pending_tracker_notifies_finished_first_once() -> None:
    tracker = _HijackPendingTracker()
    loads: list[str] = []

    def load(hijack_id: str) -> dict[str, Any]:
        loads.append(hijack_id)
        return {"hijack_id": hijack_id, "state": "finished_first"}

    tracker.observe_active_records(
        [make_latched_record()],
        load_record=lambda _hid: None,
    )
    assert tracker.pending_ids == {"h-latched"}

    tracker.observe_active_records([], load_record=load)
    assert tracker.drain_moot_notices() == (
        "finished before the hijack; nothing was held",
    )
    tracker.observe_active_records([make_latched_record()], load_record=load)
    tracker.observe_active_records([], load_record=load)
    assert tracker.drain_moot_notices() == ()
    assert loads == ["h-latched"]


def test_notify_hijack_moot_transitions_toasts_once() -> None:
    HIJACK_PENDING_TRACKER.reset()
    try:
        HIJACK_PENDING_TRACKER.observe_active_records(
            [make_latched_record()],
            load_record=lambda _hid: None,
        )
        HIJACK_PENDING_TRACKER.observe_active_records(
            [],
            load_record=lambda _hid: {"state": "finished_first"},
        )
        notifications: list[str] = []

        class App(AgentHijackActionMixin):
            def notify(self, message: str, *, severity: str = "information") -> None:
                del severity
                notifications.append(message)

        app = App()
        app._notify_hijack_moot_transitions()
        app._notify_hijack_moot_transitions()
        assert notifications == ["finished before the hijack; nothing was held"]
    finally:
        HIJACK_PENDING_TRACKER.reset()


def test_pending_tracker_ignores_cancelled_disappearance() -> None:
    tracker = _HijackPendingTracker()
    tracker.observe_active_records(
        [make_latched_record()],
        load_record=lambda _hid: None,
    )
    tracker.observe_active_records(
        [],
        load_record=lambda _hid: {"state": "cancelled"},
    )
    assert tracker.drain_moot_notices() == ()
