"""Agent Hijack ingress decisions and redirect dispatch."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agents import _hijack_action
from sase.ace.tui.actions.agents._agent_enter_models import (
    AgentEnterResolution,
    AgentEnterTarget,
)
from sase.ace.tui.actions.agents._hijack_decision import (
    cheap_hijack_ingress_available,
    hijack_ingress_available_for_footer,
    kill_modal_hijack_available,
)
from sase.ace.tui.actions.agents._hijack_action import AgentHijackActionMixin
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui._agent_hijack_action_helpers import (
    make_hijack_agent,
    make_hijack_view,
)


def test_agent_can_offer_hijack_uses_cheap_row_local_refusals() -> None:
    assert _hijack_action.agent_can_offer_hijack(make_hijack_agent())
    assert not _hijack_action.agent_can_offer_hijack(make_hijack_agent(status="DONE"))
    workflow = make_hijack_agent()
    workflow.agent_type = AgentType.WORKFLOW
    assert cheap_hijack_ingress_available(workflow)
    named = make_hijack_agent()
    named.agent_type = AgentType.NAMED_PROC
    assert not cheap_hijack_ingress_available(named)


def test_remote_hijack_ingress_copies_host_command(monkeypatch: Any) -> None:
    agent = make_hijack_agent()
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
        make_hijack_view(
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
    agent = make_hijack_agent()
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
        make_hijack_view(
            agent,
            mode="redirect",
            code="remote_row",
            redirect_op="copy_remote_command",
        ),
    )

    assert app._start_hijack_agent(agent)
    assert recorded == [("apollo", "sase-demo.1")]


def test_refused_decision_toasts_code_message_and_next_action() -> None:
    agent = make_hijack_agent()
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
        make_hijack_view(
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
    container = make_hijack_agent()
    container.agent_type = AgentType.WORKFLOW
    container.agent_name = "tailnet-t.10"
    occupant = make_hijack_agent()
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
        make_hijack_view(
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
    agent = make_hijack_agent(status="HIJACKED")
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
        make_hijack_view(
            agent, mode="redirect", code="hijacked", redirect_op="open_recovery"
        ),
    )

    assert app._start_hijack_agent(agent)
    assert opened == [agent]


def test_claimless_wait_redirect_opens_kill_and_edit_flow() -> None:
    agent = make_hijack_agent(status="WAITING")
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
        make_hijack_view(
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


def test_gate_review_redirect_dispatches_enter_gate_targets() -> None:
    agent = make_hijack_agent()
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
        make_hijack_view(
            agent, mode="redirect", code="gate_turn", redirect_op="gate_review"
        ),
    )

    assert app._start_hijack_agent(agent)
    assert len(dispatched) == 1
    occupant, resolution = dispatched[0]
    assert occupant is agent
    assert [target.kind for target in resolution.targets] == ["gate"]


def test_select_member_redirect_retargets_lone_live_member(monkeypatch: Any) -> None:
    clan = make_hijack_agent()
    clan.is_clan_container = True
    clan.agent_clan = "wave-1"
    clan.agent_name = "wave-1"
    clan.raw_suffix = None
    member = make_hijack_agent()
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
        make_hijack_view(
            clan, mode="redirect", code="clan_container", redirect_op="select_member"
        ),
    )
    app._store_hijack_decision(member, make_hijack_view(member, mode="immediate"))

    assert app._start_hijack_agent(clan)
    assert app.current_idx == 1
    assert selected[0] == 1
    assert submitted == ["wave-1--1"]
    assert member.hijack_overlay == "hijacking"


def test_show_active_hijack_redirect_toasts_decision() -> None:
    agent = make_hijack_agent()
    notifications: list[tuple[str, str]] = []

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

    app = App()
    app._store_hijack_decision(
        agent,
        make_hijack_view(
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


def test_footer_and_kill_modal_follow_cached_decision() -> None:
    agent = make_hijack_agent()
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
        make_hijack_view(
            agent,
            mode="refused",
            code="missing_capability",
            message="runner did not record hijack support",
        ),
    )
    assert hijack_ingress_available_for_footer(app, agent) is False
    assert kill_modal_hijack_available(app, agent) is False

    app._store_hijack_decision(agent, make_hijack_view(agent, mode="immediate"))
    assert hijack_ingress_available_for_footer(app, agent) is True
    assert kill_modal_hijack_available(app, agent) is True
