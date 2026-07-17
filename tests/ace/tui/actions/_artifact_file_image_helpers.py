from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.agents._panels import AgentPanelsMixin
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.graphics import TmuxPaneDecorationState


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered = False

    def __enter__(self) -> None:
        self.entered = True

    def __exit__(self, *_args) -> None:
        return None


class _ClassRecorder:
    def __init__(self) -> None:
        self.classes: set[str] = set()

    def add_class(self, class_name: str) -> None:
        self.classes.add(class_name)

    def remove_class(self, class_name: str) -> None:
        self.classes.discard(class_name)


class _ImageActionApp(AgentPanelsMixin):
    def __init__(self, image_path: str | None) -> None:
        self.current_tab = "agents"
        self.current_attempt_number: int | None = None
        self.detail = MagicMock()
        self.detail.get_current_image_path.return_value = image_path
        self.content = _ClassRecorder()
        self.agent_list = MagicMock()
        self.suspend_recorder = _SuspendRecorder()
        self.notify = MagicMock()
        self._selected_agent: Any = None
        self._artifacts: list[Any] = []
        self._artifacts_by_agent: dict[Any, list[Any]] = {}
        self.pushed: list[Any] = []
        self._artifact_file_tmux_pane_id: str | None = None
        self._artifact_file_tmux_decoration_state: TmuxPaneDecorationState | None = None
        self._agents_with_children: list[Any] = []
        self._marked_agents: set[Any] = set()

    def query_one(self, selector, *_args, **_kwargs):
        if selector == "#agents-content":
            return self.content
        if selector == "#agent-list-panel":
            return self.agent_list
        return self.detail

    def suspend(self):
        return self.suspend_recorder

    def _get_selected_agent(self):
        return self._selected_agent

    def _list_selected_artifact_files(self, agent):
        if agent is not None and id(agent) in self._artifacts_by_agent:
            return self._artifacts_by_agent[id(agent)]
        return self._artifacts

    def push_screen(self, modal, callback=None):
        self.pushed.append((modal, callback))


class _ImageQuitApp(_ImageActionApp, LifecycleMixin):
    def __init__(self) -> None:
        super().__init__(None)
        self.count_running_tasks_calls = 0
        self.did_quit = False

    def _count_running_tasks(self) -> int:
        self.count_running_tasks_calls += 1
        return 0

    def _do_quit(self) -> None:
        self.did_quit = True


def _decoration_state() -> TmuxPaneDecorationState:
    return TmuxPaneDecorationState(
        target_pane_id="%1",
        window_options=(),
        pane_titles=(),
    )
