from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.agents._fork_actions import AgentForkActionsMixin
from sase.ace.tui.actions.agents._kill_action_flow import AgentKillActionFlowMixin
from sase.ace.tui.actions.agents._remote_attention import RemoteAttentionMixin
from sase.ace.tui.actions.agents._remote_content import AgentRemoteContentMixin
from sase.ace.tui.actions.agents._remote_lifecycle import is_remote_fleet_agent
from sase.ace.tui.models.agent import Agent, AgentType
from sase.feature_flags import override_flags


def _remote_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="remote",
        project_file="/fleet/apollo/project.yml",
        status="running",
        start_time=None,
        agent_name="worker",
        raw_suffix="apollo-worker",
        fleet_origin_alias="apollo",
        fleet_origin_installation_id="sase_inst_v1_" + "a" * 64,
        fleet_exact_locator={"schema_version": 1},
        fleet_capabilities={"resource": ["lifecycle.stop", "lifecycle.fork"]},
    )


def _local_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="local",
        project_file="/tmp/project.yml",
        status="running",
        start_time=None,
        agent_name="local-worker",
        raw_suffix="local",
        pid=1234,
    )


class _KillHarness(AgentKillActionFlowMixin):
    def __init__(self, agent: Agent) -> None:
        self.current_tab = "agents"
        self._agents = [agent]
        self._agents_with_children = [agent]
        self._marked_agents = set()
        self._current_group_key = None
        self.remote_calls: list[list[Agent]] = []
        self.local_calls = 0
        self.notifications: list[str] = []

    def _get_selected_agent(self) -> Agent:
        return self._agents[0]

    def _resolve_panel_cleanup_focus(self) -> None:
        return None

    def _get_focused_group(self) -> None:
        return None

    def _confirm_remote_stop(self, agents: list[Agent]) -> None:
        self.remote_calls.append(list(agents))

    def _plan_focused_agent_cleanup(self, agent: Agent) -> SimpleNamespace:
        self.local_calls += 1
        return SimpleNamespace(dismiss_items=[], kill_items=[agent])

    def push_screen(self, _modal: object, _callback: object) -> None:
        self.local_calls += 1

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifications.append(message)


def test_remote_selection_routes_kill_to_remote_mixin() -> None:
    harness = _KillHarness(_remote_agent())
    harness.action_kill_agent()
    assert harness.remote_calls
    assert harness.local_calls == 0


def test_local_selection_keeps_local_kill_path() -> None:
    harness = _KillHarness(_local_agent())
    harness.action_kill_agent()
    assert harness.remote_calls == []
    assert harness.local_calls >= 1


def test_empty_machine_registry_does_not_treat_local_as_remote() -> None:
    agent = _local_agent()
    assert not is_remote_fleet_agent(agent)
    with override_flags(remote_dispatch=True):
        harness = _KillHarness(agent)
        harness.action_kill_agent()
    assert harness.remote_calls == []


class _ForkHarness(AgentForkActionsMixin):
    def __init__(self, agent: Agent) -> None:
        self.current_tab = "agents"
        self._agents = [agent]
        self._agents_with_children = [agent]
        self._marked_agents = set()
        self.prompt_calls: list[dict[str, object]] = []
        self.prepare_calls = 0
        self.notifications: list[str] = []

    def _get_selected_agent(self) -> Agent:
        return self._agents[0]

    def _show_prompt_input_bar_for_home(self, **kwargs: object) -> None:
        self.prompt_calls.append(kwargs)

    def _prepare_agent_prompt_target(self, *_args: object, **_kwargs: object) -> None:
        self.prepare_calls += 1

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifications.append(message)


def test_remote_selection_routes_fork_to_remote_prompt() -> None:
    harness = _ForkHarness(_remote_agent())
    harness.action_fork_agent()
    assert harness.prompt_calls
    assert harness.prompt_calls[0]["display_name"] == "Fork on apollo"
    assert harness.prepare_calls == 0
    assert harness._pending_remote_fork_identity == harness._agents[0].identity


def test_local_selection_keeps_local_fork_path(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _ForkHarness(_local_agent())
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._fork_actions.resolve_agent_prompt_target_scope",
        lambda *_args, **_kwargs: (object(), None),
    )
    harness.action_fork_agent()
    assert harness.prompt_calls == []
    assert harness.prepare_calls == 1
    assert getattr(harness, "_pending_remote_fork_identity", None) is None


class _ContentHarness(AgentRemoteContentMixin):
    def __init__(self, agent: Agent) -> None:
        self._agents = [agent]
        self.screens: list[object] = []
        self.notifications: list[str] = []

    def _get_selected_agent(self) -> Agent:
        return self._agents[0]

    def push_screen(self, screen: object) -> None:
        self.screens.append(screen)

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifications.append(message)


def test_remote_content_action_refuses_when_flag_off() -> None:
    agent = _remote_agent()
    agent.fleet_content = {"handles": [{"id": "ch1"}]}
    agent.fleet_row_revision = {
        "schema_version": 1,
        "logical_key": "k",
        "revision": 1,
    }
    harness = _ContentHarness(agent)
    with override_flags(remote_dispatch=False):
        harness.action_view_remote_agent_content()
    assert harness.screens == []
    assert any(
        "remote dispatch is disabled" in message for message in harness.notifications
    )


class _AttentionHarness(RemoteAttentionMixin):
    def __init__(self, agent: Agent) -> None:
        self._agents = [agent]
        self.screens: list[tuple[object, object]] = []
        self.notifications: list[str] = []

    def _get_selected_agent(self) -> Agent:
        return self._agents[0]

    def _agent_by_identity(self, identity: object) -> Agent | None:
        for agent in self._agents:
            if agent.identity == identity:
                return agent
        return None

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.screens.append((screen, callback))

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifications.append(message)


def _remote_agent_with_pending_question() -> Agent:
    agent = _remote_agent()
    agent.fleet_capabilities = {"resource": ["attention.answer_question"]}
    agent.fleet_attention = {
        "kind": "question",
        "state": "pending",
        "request_key": {"request_id": "question-0001"},
        "revision": 1,
        "title": "What next?",
    }
    return agent


def test_answer_remote_attention_refuses_when_flag_off() -> None:
    harness = _AttentionHarness(_remote_agent_with_pending_question())
    with override_flags(remote_dispatch=False):
        harness.action_answer_remote_attention()
    assert harness.screens == []
    assert any(
        "remote dispatch is disabled" in message for message in harness.notifications
    )


def test_answer_remote_attention_refuses_without_pending_entry() -> None:
    harness = _AttentionHarness(_remote_agent())
    with override_flags(remote_dispatch=True):
        harness.action_answer_remote_attention()
    assert harness.screens == []
    assert any(
        "pending question or gate" in message for message in harness.notifications
    )


def test_answer_remote_attention_opens_modal_for_pending_question() -> None:
    harness = _AttentionHarness(_remote_agent_with_pending_question())
    with override_flags(remote_dispatch=True):
        harness.action_answer_remote_attention()
    assert len(harness.screens) == 1
    from sase.ace.tui.modals.remote_attention_modal import RemoteAttentionModal

    modal, _callback = harness.screens[0]
    assert isinstance(modal, RemoteAttentionModal)
