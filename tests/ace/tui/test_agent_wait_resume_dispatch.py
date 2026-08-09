"""Tests for Agents-tab key dispatch related to wait and fork actions."""

from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.actions.hints._hooks import HookEditingMixin


class _FakeAgentForkDispatchApp(BaseActionsMixin, HookEditingMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.patches = [object()]
        self.fork_calls = 0
        self.retry_edit_calls = 0

    def action_fork_agent(self) -> None:
        self.fork_calls += 1

    def _retry_edit_agent(self) -> None:
        self.retry_edit_calls += 1


def test_run_workflow_on_agents_dispatches_retry_edit_and_does_not_fork() -> None:
    app = _FakeAgentForkDispatchApp()

    BaseActionsMixin.action_run_workflow(app)

    assert app.retry_edit_calls == 1
    assert app.fork_calls == 0


def test_edit_hooks_on_agents_dispatches_to_fork() -> None:
    app = _FakeAgentForkDispatchApp()

    HookEditingMixin.action_edit_hooks(app)

    assert app.fork_calls == 1
