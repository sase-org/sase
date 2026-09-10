from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.actions.agents._fork_actions import AgentForkActionsMixin
from sase.ace.tui.actions.agents._kill_action_flow import AgentKillActionFlowMixin
from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
from sase.ace.tui.actions.agents._remote_attention import RemoteAttentionMixin
from sase.ace.tui.actions.agents._remote_content import AgentRemoteContentMixin
from sase.ace.tui.actions.agents._remote_lifecycle import is_remote_fleet_agent
from sase.ace.tui.actions.proposal_rebase import ProposalRebaseMixin
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import KeybindingFooter


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


def _remote_agent_with_shared_capabilities() -> Agent:
    agent = _remote_agent()
    agent.fleet_capabilities = {
        "resource": [
            "lifecycle.stop",
            "lifecycle.retry",
            "lifecycle.fork",
            "attention.answer_question",
        ]
    }
    agent.fleet_content = {"handles": [{"id": "ch1"}]}
    agent.fleet_row_revision = {
        "schema_version": 1,
        "logical_key": "k",
        "revision": 1,
    }
    agent.fleet_attention = {
        "kind": "question",
        "state": "pending",
        "request_key": {"request_id": "question-0001"},
    }
    return agent


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


class _RunWorkflowHarness(BaseActionsMixin):
    def __init__(self, agent: Agent) -> None:
        self.current_tab = "agents"
        self._agents = [agent]
        self.current_idx = 0
        self.remote_retry_calls = 0
        self.local_retry_calls = 0

    def _get_selected_agent(self) -> Agent:
        return self._agents[0]

    def action_retry_remote_agent(self) -> None:
        self.remote_retry_calls += 1

    def _retry_edit_agent(self) -> None:
        self.local_retry_calls += 1


def test_agents_retry_key_routes_remote_selection_to_owner_retry() -> None:
    harness = _RunWorkflowHarness(_remote_agent_with_shared_capabilities())
    harness.action_run_workflow()
    assert harness.remote_retry_calls == 1
    assert harness.local_retry_calls == 0


def test_agents_retry_key_keeps_local_retry_path() -> None:
    harness = _RunWorkflowHarness(_local_agent())
    harness.action_run_workflow()
    assert harness.remote_retry_calls == 0
    assert harness.local_retry_calls == 1


class _AcceptHarness(ProposalRebaseMixin):
    def __init__(self, agent: Agent) -> None:
        self.current_tab = "agents"
        self._agents = [agent]
        self.current_idx = 0
        self.remote_attention_calls = 0
        self.local_hitl_calls = 0

    def _refocus_existing_hint_bar(self) -> bool:
        return False

    def action_answer_remote_attention(self) -> None:
        self.remote_attention_calls += 1

    def _answer_workflow_hitl(self, _agent: Agent) -> None:
        self.local_hitl_calls += 1


def test_agents_accept_key_routes_remote_attention_to_owner() -> None:
    harness = _AcceptHarness(_remote_agent_with_pending_question())
    harness.action_accept_proposal()
    assert harness.remote_attention_calls == 1
    assert harness.local_hitl_calls == 0


def test_agents_accept_key_keeps_local_hitl_path() -> None:
    agent = _local_agent()
    agent.status = "WAITING INPUT"
    harness = _AcceptHarness(agent)
    harness.action_accept_proposal()
    assert harness.remote_attention_calls == 0
    assert harness.local_hitl_calls == 1


class _PanelDetailHarness(AgentPanelDetailMixin):
    def __init__(self, agent: Agent) -> None:
        self.current_tab = "agents"
        self._agents = [agent]
        self._marked_agents = set()
        self.remote_content_calls = 0
        self.opened_paths: list[list[str]] = []
        self.notifications: list[str] = []

    def _get_selected_agent(self) -> Agent:
        return self._agents[0]

    def action_view_remote_agent_content(self) -> None:
        self.remote_content_calls += 1

    def _open_agent_chat_paths(self, chat_paths: list[str]) -> None:
        self.opened_paths.append(chat_paths)

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifications.append(message)


def test_agents_edit_chat_key_routes_remote_selection_to_content() -> None:
    harness = _PanelDetailHarness(_remote_agent_with_shared_capabilities())
    harness._open_agent_chat()
    assert harness.remote_content_calls == 1
    assert harness.opened_paths == []


def test_agents_edit_chat_key_keeps_local_finished_chat_path() -> None:
    agent = _local_agent()
    agent.status = "DONE"
    agent.response_path = "/tmp/local-chat.md"
    harness = _PanelDetailHarness(agent)
    harness._open_agent_chat()
    assert harness.remote_content_calls == 0
    assert harness.opened_paths == [["/tmp/local-chat.md"]]


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


def test_remote_content_action_opens_modal_for_available_content() -> None:
    agent = _remote_agent()
    agent.fleet_content = {"handles": [{"id": "ch1"}]}
    agent.fleet_row_revision = {
        "schema_version": 1,
        "logical_key": "k",
        "revision": 1,
    }
    harness = _ContentHarness(agent)
    harness.action_view_remote_agent_content()
    assert len(harness.screens) == 1
    from sase.ace.tui.modals.remote_content_modal import RemoteContentModal

    assert isinstance(harness.screens[0], RemoteContentModal)


class _AttentionHarness(RemoteAttentionMixin):
    def __init__(self, agent: Agent) -> None:
        self._agents = [agent]
        self.screens: list[tuple[object, object]] = []
        self.notifications: list[str] = []
        self._fleet_attention_inventory_refresh_running = False
        self._fleet_attention_inventory_refresh_pending = False
        self._fleet_attention_inventory_last_error = None
        self._dirty_notifications = False
        self.notification_snapshot_refreshes = 0

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

    def _schedule_notification_snapshot_refresh(self) -> None:
        self.notification_snapshot_refreshes += 1


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


def test_answer_remote_attention_refuses_without_pending_entry() -> None:
    harness = _AttentionHarness(_remote_agent())
    harness.action_answer_remote_attention()
    assert harness.screens == []
    assert any(
        "pending question or gate" in message for message in harness.notifications
    )


def test_answer_remote_attention_opens_modal_for_pending_question() -> None:
    harness = _AttentionHarness(_remote_agent_with_pending_question())
    harness.action_answer_remote_attention()
    assert len(harness.screens) == 1
    from sase.ace.tui.modals.remote_attention_modal import RemoteAttentionModal

    modal, _callback = harness.screens[0]
    assert isinstance(modal, RemoteAttentionModal)


def test_footer_shows_shared_remote_row_actions() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))
    bindings = set(
        footer._compute_agent_bindings(_remote_agent_with_shared_capabilities())
    )
    assert (footer._kd("kill_agent"), "stop apollo") in bindings
    assert (footer._kd("run_workflow"), "retry") in bindings
    assert (footer._kd("edit_hooks"), "fork") in bindings
    assert (footer._kd("edit_spec"), "content") in bindings
    assert (footer._kd("accept_proposal"), "answer") in bindings
    assert (footer._kd("rename_cl"), "name") not in bindings
    assert (footer._kd("open_tmux"), "tmux (primary)") not in bindings


@pytest.mark.asyncio
async def test_attention_inventory_poll_marks_notifications_dirty_on_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.agents import _remote_attention as remote_attention

    harness = _AttentionHarness(_remote_agent())
    monkeypatch.setattr(
        remote_attention,
        "fetch_remote_attention_inventory",
        lambda **_kwargs: {"schema_version": 1, "hosts": []},
    )
    monkeypatch.setattr(
        remote_attention,
        "reconcile_remote_attention_inbox",
        lambda _response: SimpleNamespace(changed=True),
    )

    changed = await harness._poll_fleet_attention_inventory(source="auto_refresh")

    assert changed is True
    assert harness._dirty_notifications is True
    assert harness.notification_snapshot_refreshes == 1
