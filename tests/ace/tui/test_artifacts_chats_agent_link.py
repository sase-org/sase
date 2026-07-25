"""Chat-to-agent navigation and dismissed-agent revival coverage."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from sase.ace.tui.actions.artifacts_chats import ArtifactsChatsActionsMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.history.chat_catalog_provenance import ChatCatalogEntry
from tests.ace.tui._artifacts_chats_helpers import chat_entry


def _agent(
    entry: ChatCatalogEntry,
    *,
    cl_name: str,
    agent_type: AgentType = AgentType.WORKFLOW,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/projects/alpha/alpha.sase",
        status="DONE",
        start_time=datetime(2026, 7, 24, 12, 0),
        workflow="code",
        raw_suffix=entry.basename,
        artifacts_dir=entry.agent_artifact_dir,
        agent_name=entry.agent_local_name,
    )


class _Pane:
    def __init__(self, entry: ChatCatalogEntry | None) -> None:
        self.selected_entry = entry


class _FakeApp(ArtifactsChatsActionsMixin):
    def __init__(self, entry: ChatCatalogEntry | None) -> None:
        self.pane = _Pane(entry)
        self.current_tab = "changespecs"
        self.current_idx = 0
        self._agents: list[Agent] = []
        self._dismissed_agent_objects: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self.revived: list[Agent] = []
        self.reloaded_agent: Agent | None = None
        self.saved_positions = 0
        self.notifications: list[tuple[str, str]] = []

    def _chats_pane(self) -> _Pane:
        return self.pane

    def _save_current_tab_position(self) -> None:
        self.saved_positions += 1

    def _do_revive_agent(self, agent: Agent) -> None:
        self.revived.append(agent)
        if self.reloaded_agent is not None:
            self._agents.append(self.reloaded_agent)

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))


def test_active_chat_agent_jumps_without_revival() -> None:
    entry = chat_entry("active")
    target = _agent(entry, cl_name="target")
    app = _FakeApp(entry)
    app._agents = [_agent(chat_entry("other"), cl_name="other"), target]

    app.action_chats_open_agent()

    assert app.current_tab == "agents"
    assert app.current_idx == 1
    assert app.saved_positions == 1
    assert app.revived == []
    assert app.notifications == []


def test_dismissed_chat_agent_is_revived_once_then_selected_by_suffix() -> None:
    entry = chat_entry("dismissed")
    dismissed = _agent(entry, cl_name="old", agent_type=AgentType.WORKFLOW)
    reloaded = _agent(entry, cl_name="new", agent_type=AgentType.RUNNING)
    app = _FakeApp(entry)
    app._agents = [_agent(chat_entry("other"), cl_name="other")]
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    app.reloaded_agent = reloaded

    app.action_chats_open_agent()

    assert app.revived == [dismissed]
    assert app.current_tab == "agents"
    assert app.current_idx == 1
    assert app._agents[app.current_idx] is reloaded
    assert app.notifications == []


def test_chat_without_agent_notifies_and_preserves_tab_state() -> None:
    entry = replace(
        chat_entry("unlinked"),
        agent_artifact_dir=None,
        agent_local_name=None,
        agent_global_name=None,
    )
    app = _FakeApp(entry)
    original_idx = app.current_idx

    app.action_chats_open_agent()

    assert app.current_tab == "changespecs"
    assert app.current_idx == original_idx
    assert app.saved_positions == 0
    assert app.revived == []
    assert app.notifications == [("No agent is associated with this chat", "warning")]


def test_remote_chat_without_local_artifact_explains_source_machine() -> None:
    entry = replace(
        chat_entry("imported", provenance="remote", machine="zeus"),
        agent_artifact_dir=None,
        agent_local_name=None,
        agent_global_name=None,
    )
    app = _FakeApp(entry)

    app.action_chats_open_agent()

    assert app.current_tab == "changespecs"
    assert app.saved_positions == 0
    assert app.notifications == [
        (
            "This chat was imported from zeus and has no local agent artifact",
            "warning",
        )
    ]
