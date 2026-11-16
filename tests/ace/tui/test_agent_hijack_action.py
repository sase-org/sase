"""Agents-tab ingress for durable Agent Hijack operations."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents import _hijack_action
from sase.ace.tui.actions.agents._agent_enter_models import (
    AgentEnterResolution,
    AgentEnterTarget,
)
from sase.ace.tui.actions.agents._hijack_decision import (
    HijackDecisionView,
    cheap_hijack_ingress_available,
    hijack_ingress_available_for_footer,
    kill_modal_hijack_available,
    row_has_pending_latch,
)
from sase.ace.tui.actions.agents._hijack_action import AgentHijackActionMixin
from sase.ace.tui.actions.agents._hijack_pending_panel import (
    _CANCEL_RESULT,
    _FORCE_RESULT,
    _FORCE_WARNING,
    _pending_hijack_choices,
    _pending_latch_force_eligible,
    apply_hijack_proc_completion,
)
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


def _agent(*, status: str = "RUNNING") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/project.sase",
        status=status,
        start_time=datetime(2026, 11, 3, 10, 0, 0),
        workspace_num=4,
        pid=421,
        raw_suffix="20261103100000",
        agent_name="sase-demo.1",
    )


def _view(
    agent: Agent,
    *,
    mode: str,
    code: str | None = None,
    message: str | None = None,
    next_action: str | None = None,
    redirect_op: str | None = None,
    occupant_name: str | None = None,
) -> HijackDecisionView:
    return HijackDecisionView(
        identity=agent.identity,
        roster_generation=0,
        occupant_name=occupant_name or agent.agent_name,
        occupant_reason="test occupant",
        workspace_num=agent.workspace_num,
        decision={
            "mode": mode,
            "code": code,
            "message": message,
            "next_action": next_action,
            "redirect_op": redirect_op,
            "adapter": "llm" if mode == "immediate" else None,
        },
    )


def test_agent_can_offer_hijack_uses_cheap_row_local_refusals() -> None:
    assert _hijack_action.agent_can_offer_hijack(_agent())
    assert not _hijack_action.agent_can_offer_hijack(_agent(status="DONE"))
    workflow = _agent()
    workflow.agent_type = AgentType.WORKFLOW
    assert cheap_hijack_ingress_available(workflow)
    named = _agent()
    named.agent_type = AgentType.NAMED_PROC
    assert not cheap_hijack_ingress_available(named)


def test_hijack_submission_shows_pending_and_stop_failed_rows(
    monkeypatch: Any,
) -> None:
    agent = _agent()
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
    app._store_hijack_decision(agent, _view(agent, mode="immediate"))

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
    agent = _agent(status="HIJACKED")
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
    agent = _agent()
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
    agent = _agent(status="HIJACKED")
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
    agent = _agent(status="HIJACKED")
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


def test_remote_hijack_ingress_copies_host_command(monkeypatch: Any) -> None:
    agent = _agent()
    agent.fleet_origin_alias = "athena"
    notifications: list[str] = []
    copied: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "sase.agent.hijack.referral.record_remote_hijack_referral",
        lambda *_args, **_kwargs: None,
    )

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            del severity
            notifications.append(message)

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard.schedule_copy_delivery",
        lambda _owner, value, **kwargs: copied.append((value, kwargs)),
    )
    app._store_hijack_decision(
        agent,
        _view(
            agent,
            mode="redirect",
            code="remote_row",
            redirect_op="copy_remote_command",
        ),
    )

    assert app._start_hijack_agent(agent)

    assert copied[0][0] == "sase agent hijack sase-demo.1"
    assert copied[0][1]["task_name"] == "copy-hijack-command-athena"
    assert "Agent runs on athena" in notifications[0]


def test_remote_hijack_ingress_records_a_local_referral(
    monkeypatch: Any,
) -> None:
    from sase.agent.hijack import referral as referral_mod

    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(
        referral_mod,
        "record_remote_hijack_referral",
        lambda alias, name, **_kwargs: recorded.append((alias, name)),
    )
    agent = _agent()
    agent.fleet_origin_alias = "apollo"

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard.schedule_copy_delivery",
        lambda *_args, **_kwargs: None,
    )
    app._store_hijack_decision(
        agent,
        _view(
            agent,
            mode="redirect",
            code="remote_row",
            redirect_op="copy_remote_command",
        ),
    )

    assert app._start_hijack_agent(agent)
    assert recorded == [("apollo", "sase-demo.1")]


def test_refused_decision_toasts_code_message_and_next_action() -> None:
    agent = _agent()
    notifications: list[tuple[str, str]] = []

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

        def _refresh_agents_display(
            self, *, list_changed: bool, defer_detail: bool
        ) -> None:
            del list_changed, defer_detail

    app = App()
    app._store_hijack_decision(
        agent,
        _view(
            agent,
            mode="refused",
            code="monitor_turn",
            message="monitor turns cannot be hijacked yet",
            next_action="stop it with x or wait for its follow-up",
        ),
    )

    assert app._start_hijack_agent(agent) is False
    assert notifications == [
        (
            "monitor_turn: monitor turns cannot be hijacked yet · "
            "stop it with x or wait for its follow-up",
            "warning",
        )
    ]


def test_hijack_submits_occupying_member_name(monkeypatch: Any) -> None:
    container = _agent()
    container.agent_type = AgentType.WORKFLOW
    container.agent_name = "tailnet-t.10"
    occupant = _agent()
    occupant.agent_name = "tailnet-t.10--mon-3"
    occupant.raw_suffix = "20261115164108"
    occupant.agent_session = "tailnet-t.10"
    submitted: list[dict[str, Any]] = []

    class App(AgentHijackActionMixin):
        _agents_with_children = [container, occupant]

        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

        def _refresh_agents_display(
            self, *, list_changed: bool, defer_detail: bool
        ) -> None:
            del list_changed, defer_detail

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._roster_generation.notify_roster_status_mutation",
        lambda _app: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_durable.submit_agent_hijack",
        lambda _app, **kwargs: submitted.append(kwargs) or True,
    )
    app._store_hijack_decision(
        container,
        _view(
            container,
            mode="immediate",
            occupant_name="tailnet-t.10--mon-3",
        ),
    )

    assert app._start_hijack_agent(container)
    assert [row["name"] for row in submitted] == ["tailnet-t.10--mon-3"]
    assert submitted[0]["identity"] == str(occupant.identity)
    assert submitted[0]["session_name"] == "tailnet-t.10"
    assert occupant.hijack_overlay == "hijacking"


def test_open_recovery_redirect_opens_panel(monkeypatch: Any) -> None:
    agent = _agent(status="HIJACKED")
    opened: list[Agent] = []

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._hijack_recovery_panel.open_hijack_recovery_panel",
        lambda _app, row: opened.append(row),
    )
    app._store_hijack_decision(
        agent,
        _view(agent, mode="redirect", code="hijacked", redirect_op="open_recovery"),
    )

    assert app._start_hijack_agent(agent)
    assert opened == [agent]


def test_claimless_wait_redirect_opens_kill_and_edit_flow() -> None:
    agent = _agent(status="WAITING")
    agent.workspace_num = 0
    opened: list[Agent] = []
    messages: list[str] = []

    class App(AgentHijackActionMixin):
        _agents_with_children = [agent]

        def notify(self, message: str, *, severity: str = "information") -> None:
            messages.append(message)

        def _select_hijack_retarget(self, row: Agent) -> None:
            assert row is agent

        def _kill_and_edit_agent(self, row: Agent) -> None:
            opened.append(row)

    app = App()
    app._store_hijack_decision(
        agent,
        _view(
            agent,
            mode="redirect",
            code="nothing_to_keep",
            message="waiting turn has no numbered workspace to keep",
            redirect_op="kill_and_edit",
        ),
    )

    assert app._start_hijack_agent(agent)
    assert opened == [agent]
    assert any("nothing_to_keep" in message for message in messages)


def test_footer_and_kill_modal_follow_cached_decision() -> None:
    agent = _agent()
    agent.agent_type = AgentType.WORKFLOW

    class BareApp:
        pass

    class App(AgentHijackActionMixin):
        pass

    bare = BareApp()
    assert hijack_ingress_available_for_footer(bare, agent) is True
    assert kill_modal_hijack_available(bare, agent) is True

    app = App()

    app._store_hijack_decision(
        agent,
        _view(
            agent,
            mode="refused",
            code="missing_capability",
            message="runner did not record hijack support",
        ),
    )
    assert hijack_ingress_available_for_footer(app, agent) is False
    assert kill_modal_hijack_available(app, agent) is False

    app._store_hijack_decision(agent, _view(agent, mode="immediate"))
    assert hijack_ingress_available_for_footer(app, agent) is True
    assert kill_modal_hijack_available(app, agent) is True


def test_collapsed_session_mirrors_hijack_record() -> None:
    parent = _agent()
    parent.agent_type = AgentType.WORKFLOW
    parent.agent_name = "tailnet-t.10"
    parent.agent_session_role = "root"
    child = _agent(status="HIJACKED")
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


def test_gate_review_redirect_dispatches_enter_gate_targets() -> None:
    agent = _agent()
    dispatched: list[tuple[Agent, AgentEnterResolution]] = []

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

        def _agent_enter_resolution(self, occupant: Agent) -> AgentEnterResolution:
            del occupant
            return AgentEnterResolution(
                targets=(
                    AgentEnterTarget(
                        kind="gate",
                        source="gate_row",
                        key="g-1",
                        label="Approve plan",
                    ),
                    AgentEnterTarget(
                        kind="patch",
                        source="patch",
                        key="feature",
                        label="Open Patch",
                    ),
                )
            )

        def _dispatch_agent_enter_resolution(
            self, occupant: Agent, resolution: AgentEnterResolution
        ) -> None:
            dispatched.append((occupant, resolution))

    app = App()
    app._store_hijack_decision(
        agent,
        _view(agent, mode="redirect", code="gate_turn", redirect_op="gate_review"),
    )

    assert app._start_hijack_agent(agent)
    assert len(dispatched) == 1
    occupant, resolution = dispatched[0]
    assert occupant is agent
    assert [target.kind for target in resolution.targets] == ["gate"]


def test_select_member_redirect_retargets_lone_live_member(monkeypatch: Any) -> None:
    clan = _agent()
    clan.is_clan_container = True
    clan.agent_clan = "wave-1"
    clan.agent_name = "wave-1"
    clan.raw_suffix = None
    member = _agent()
    member.agent_name = "wave-1--1"
    member.agent_clan = "wave-1"
    member.raw_suffix = "20261115170000"
    submitted: list[str] = []
    selected: list[int] = []

    class App(AgentHijackActionMixin):
        current_idx = 0
        _agents = [clan, member]
        _agents_with_children = [clan, member]

        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

        def _refresh_agents_display(
            self, *, list_changed: bool, defer_detail: bool
        ) -> None:
            del list_changed, defer_detail
            selected.append(self.current_idx)

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._roster_generation.notify_roster_status_mutation",
        lambda _app: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_durable.submit_agent_hijack",
        lambda _app, **kwargs: submitted.append(kwargs["name"]) or True,
    )
    app._store_hijack_decision(
        clan,
        _view(
            clan, mode="redirect", code="clan_container", redirect_op="select_member"
        ),
    )
    app._store_hijack_decision(member, _view(member, mode="immediate"))

    assert app._start_hijack_agent(clan)
    assert app.current_idx == 1
    assert selected[0] == 1
    assert submitted == ["wave-1--1"]
    assert member.hijack_overlay == "hijacking"


def test_show_active_hijack_redirect_toasts_decision() -> None:
    agent = _agent()
    notifications: list[tuple[str, str]] = []

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

    app = App()
    app._store_hijack_decision(
        agent,
        _view(
            agent,
            mode="redirect",
            code="active_hijack",
            message="a hijack is already in progress",
            next_action="open recovery with Enter",
            redirect_op="show_active_hijack",
        ),
    )

    assert app._start_hijack_agent(agent)
    assert notifications == [
        (
            "active_hijack: a hijack is already in progress · open recovery with Enter",
            "warning",
        )
    ]


def _latched_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "hijack_id": "h-latched",
        "agent_name": "sase-demo.1",
        "state": "latched",
        "boundary": "handoff",
        "target_key": "proj:session-1",
        "workspace_num": 4,
        "latched_at": 1_000_000,
    }
    record.update(overrides)
    return record


def test_latched_ledger_record_projects_pending_overlay_on_member_and_container(
    tmp_path: Any, monkeypatch: Any
) -> None:
    HIJACK_PENDING_TRACKER.reset()
    try:
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        parent = _agent()
        parent.agent_name = "session-root"
        parent.agent_session = "session-root"
        parent.agent_session_role = "root"
        child = _agent()
        child.agent_name = "session-root--1"
        child.agent_session = "session-root"
        child.artifacts_dir = str(artifacts_dir)
        parent.followup_agents = [child]
        records = [
            _latched_record(
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
        [_latched_record()],
        load_record=lambda _hid: None,
    )
    assert tracker.pending_ids == {"h-latched"}

    tracker.observe_active_records([], load_record=load)
    assert tracker.drain_moot_notices() == (
        "finished before the hijack; nothing was held",
    )
    tracker.observe_active_records([_latched_record()], load_record=load)
    tracker.observe_active_records([], load_record=load)
    assert tracker.drain_moot_notices() == ()
    assert loads == ["h-latched"]


def test_notify_hijack_moot_transitions_toasts_once() -> None:
    HIJACK_PENDING_TRACKER.reset()
    try:
        HIJACK_PENDING_TRACKER.observe_active_records(
            [_latched_record()],
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
        [_latched_record()],
        load_record=lambda _hid: None,
    )
    tracker.observe_active_records(
        [],
        load_record=lambda _hid: {"state": "cancelled"},
    )
    assert tracker.drain_moot_notices() == ()


def test_footer_and_kill_modal_offer_hijack_for_pending_latch() -> None:
    agent = _agent()
    agent.hijack_overlay = "pending"
    agent.hijack_record = _latched_record()

    class App(AgentHijackActionMixin):
        pass

    app = App()
    app._store_hijack_decision(
        agent,
        _view(
            agent,
            mode="refused",
            code="finalizing_turn",
            message="finalizing turns cannot be hijacked yet",
        ),
    )
    assert row_has_pending_latch(agent) is True
    assert hijack_ingress_available_for_footer(app, agent) is True
    assert kill_modal_hijack_available(app, agent) is True


def test_pending_row_opens_cancel_force_panel(monkeypatch: Any) -> None:
    agent = _agent()
    agent.hijack_overlay = "pending"
    agent.hijack_record = _latched_record()
    opened: list[Agent] = []

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

        def _get_selected_agent(self) -> Agent:
            return agent

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._hijack_pending_panel.open_pending_hijack_panel",
        lambda _app, row: opened.append(row) or True,
    )
    app._store_hijack_decision(
        agent,
        _view(agent, mode="refused", code="finalizing_turn"),
    )

    assert app._start_hijack_agent() is True
    assert opened == [agent]


def test_pending_ingress_skips_when_selection_moves(monkeypatch: Any) -> None:
    pending = _agent()
    pending.hijack_overlay = "pending"
    pending.hijack_record = _latched_record()
    other = _agent()
    other.agent_name = "other.1"
    other.raw_suffix = "20261103100001"
    opened: list[Agent] = []
    selected: list[Agent] = [pending]

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

        def _get_selected_agent(self) -> Agent:
            current = selected[0]
            selected[0] = other
            return current

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._hijack_pending_panel.open_pending_hijack_panel",
        lambda _app, row: opened.append(row) or True,
    )
    assert app._start_hijack_agent() is False
    assert opened == []
    selected[0] = pending
    assert app._start_hijack_agent(pending) is True
    assert opened == [pending]


def test_latched_occupying_completion_stays_pending(monkeypatch: Any) -> None:
    agent = _agent()
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
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_durable.submit_agent_hijack",
        lambda _app, **kwargs: callbacks.append(kwargs["on_complete"]) or True,
    )
    app._store_hijack_decision(agent, _view(agent, mode="latched"))

    assert app._start_hijack_agent(agent)
    assert agent.hijack_overlay == "pending"

    callbacks[0](
        SimpleNamespace(
            payload={
                "status": "latched",
                "hijack_id": "h-latched",
                "record": _latched_record(),
            },
            message="",
            success=True,
        )
    )

    assert agent.hijack_overlay == "pending"
    assert agent.hijack_stop_failed is False
    assert agent.hijack_id == "h-latched"
    assert notifications == [
        ("Hijack latched; waiting for a safe boundary", "information")
    ]


def test_refused_force_keeps_pending_overlay() -> None:
    agent = _agent()
    agent.hijack_overlay = "pending"
    agent.hijack_record = _latched_record()
    notifications: list[tuple[str, str]] = []

    class App:
        def notify(self, message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

    apply_hijack_proc_completion(
        App(),
        agent,
        agent,
        SimpleNamespace(
            payload={
                "status": "refused",
                "code": "force_too_early",
                "severity": "warning",
            },
            message="the pending latch is younger than 120 seconds",
            success=False,
        ),
    )

    assert agent.hijack_overlay == "pending"
    assert agent.hijack_stop_failed is False
    assert notifications == [
        ("the pending latch is younger than 120 seconds", "warning")
    ]


def test_moot_completion_toasts_exact_phrase() -> None:
    agent = _agent()
    agent.hijack_overlay = "pending"
    notifications: list[tuple[str, str]] = []

    class App:
        def notify(self, message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

    apply_hijack_proc_completion(
        App(),
        agent,
        agent,
        SimpleNamespace(
            payload={"status": "finished_first"},
            message="some other wording",
            success=True,
        ),
    )

    assert agent.hijack_overlay is None
    assert notifications == [
        ("finished before the hijack; nothing was held", "information")
    ]


def test_delayed_completion_applies_to_current_identity_row() -> None:
    original = _agent()
    original.hijack_overlay = "pending"
    original.hijack_record = _latched_record()
    refreshed = _agent()
    refreshed.hijack_overlay = "pending"
    refreshed.hijack_record = _latched_record()
    notifications: list[str] = []

    class App(AgentHijackActionMixin):
        _agents_with_children = [refreshed]
        _agents = [refreshed]

        def notify(self, message: str, *, severity: str = "information") -> None:
            del severity
            notifications.append(message)

        def _refresh_agents_display(
            self, *, list_changed: bool, defer_detail: bool
        ) -> None:
            del list_changed, defer_detail

    app = App()
    apply_hijack_proc_completion(
        app,
        app._hijack_row_for_identity(original.identity) or original,
        app._hijack_row_for_identity(original.identity) or original,
        SimpleNamespace(
            payload={"status": "cancelled"},
            message="latch cancelled",
            success=True,
        ),
    )

    assert refreshed.hijack_overlay is None
    assert original.hijack_overlay == "pending"
    assert notifications == ["latch cancelled"]


def test_pending_force_choice_appears_only_after_120s(monkeypatch: Any) -> None:
    record = _latched_record()
    monkeypatch.setattr(
        "sase.agent.hijack.core.hijack_latch_force_eligibility",
        lambda _record, now: {
            "eligible": now >= 1_000_120,
            "age_seconds": now - 1_000_000,
            "threshold_seconds": 120,
        },
    )
    assert _pending_latch_force_eligible(record, now=1_000_119) is False
    young = _pending_hijack_choices(record, now=1_000_119)
    assert [choice.result for choice in young] == [_CANCEL_RESULT]
    assert _pending_latch_force_eligible(record, now=1_000_120) is True
    aged = _pending_hijack_choices(record, now=1_000_120)
    assert [choice.result for choice in aged] == [_CANCEL_RESULT, _FORCE_RESULT]
    assert aged[1].detail == _FORCE_WARNING
    assert aged[1].hotkey == "n"


def test_pending_cancel_submits_durable_cancel(monkeypatch: Any) -> None:
    agent = _agent()
    agent.hijack_overlay = "pending"
    agent.hijack_record = _latched_record()
    submitted: list[dict[str, Any]] = []
    pushed: list[Any] = []

    class App(AgentHijackActionMixin):
        _agents_with_children = [agent]

        def notify(self, message: str, *, severity: str = "information") -> None:
            del message, severity

        def push_screen(self, modal: Any, callback: Any) -> None:
            pushed.append(modal)
            callback(_CANCEL_RESULT)

        def _refresh_agents_display(
            self, *, list_changed: bool, defer_detail: bool
        ) -> None:
            del list_changed, defer_detail

    app = App()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._roster_generation.notify_roster_status_mutation",
        lambda _app: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_durable.submit_agent_hijack",
        lambda _app, **kwargs: submitted.append(kwargs) or True,
    )
    monkeypatch.setattr(
        "sase.agent.hijack.core.hijack_latch_force_eligibility",
        lambda *_args, **_kwargs: {"eligible": False},
    )

    from sase.ace.tui.actions.agents._hijack_pending_panel import (
        open_pending_hijack_panel,
    )

    assert open_pending_hijack_panel(app, agent) is True
    assert submitted[0]["action"] == "cancel"
    assert submitted[0]["hijack_id"] == "h-latched"
    assert submitted[0]["target_key"] == "proj:session-1"
    assert submitted[0]["name"] == "sase-demo.1"
    assert pushed[0]._title_text.startswith("⏏ Pending hijack")


def test_help_lists_pending_cancel_and_force() -> None:
    from sase.ace.tui.keymaps import load_keymap_registry
    from sase.ace.tui.modals.help_modal.agents_mode_sections import mode_sections

    boxes = dict(mode_sections(load_keymap_registry({})))
    leader = next(
        rows for title, rows in boxes.items() if title.startswith("Leader Mode")
    )
    descriptions = [description for _key, description in leader]
    assert "Hijack, cancel, or force latch" in descriptions
    assert len("Hijack, cancel, or force latch") <= 32
