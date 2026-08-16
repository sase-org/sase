"""Regression coverage for prompt-context release at durable launch submit."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.actions.agent_workflow._agent_launch import AgentLaunchMixin

from tests.ace.tui._agent_launch_helpers import _fake_context
from tests.ace.tui._event_handlers_dirty_flags_helpers import _FakeApp as _RefreshApp


class _SubmitBoundaryApp(AgentLaunchMixin, _RefreshApp):
    """Drive real launch submission while stubbing only durable proc creation."""

    def __init__(self) -> None:
        _RefreshApp.__init__(self, watcher_active=False)
        self._prompt_context = _fake_context()
        self._bulk_patches = None
        self._last_custom_agent_selection = None
        self.notifications: list[tuple[str, str | None]] = []
        self.unmount_calls: list[str] = []
        self.durable_submissions: list[tuple[list[str], dict[str, Any]]] = []
        self._screen_stack = [object()]
        self.screen = object()

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def _unmount_prompt_bar_after_submit(self) -> None:
        self.unmount_calls.append("submit")

    def _submit_durable_proc(self, argv: list[str], **kwargs: Any) -> object:
        self.durable_submissions.append((argv, kwargs))
        return SimpleNamespace(proc_id=f"proc-{len(self.durable_submissions)}")


def test_real_submit_path_releases_context_and_reopens_gates() -> None:
    app = _SubmitBoundaryApp()
    app._spawn_auto_refresh_task = lambda: app.refresh_calls.append("spawn")  # type: ignore[method-assign]

    app._launch_resolved_prompt("plain prompt")

    assert app.unmount_calls == ["submit"]
    assert app._prompt_context is None
    assert app._prompt_input_active() is False
    assert len(app.durable_submissions) == 1
    _argv, kwargs = app.durable_submissions[0]
    assert kwargs["request"]["prompt"] == "plain prompt"
    assert kwargs["request"]["workflow"].startswith("ace(run)-")
    assert app._launch_submitted_prompts == {"proc-1": "plain prompt"}

    assert (
        check_app_action(app, "start_agent_from_patch", (), lambda *_args: True)
        is not False
    )
    assert check_app_action(app, "search_forward", (), lambda *_args: True) is not False

    app._on_auto_refresh()
    assert app.refresh_calls == ["spawn"]
