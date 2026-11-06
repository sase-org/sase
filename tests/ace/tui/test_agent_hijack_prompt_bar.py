"""Hijack Instruct/Edit prompt-bar flows (phase tui_prompt)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents import _hijack_prompt_bar as hijack_bar
from sase.ace.tui.actions.agents._hijack_prompt_bar import (
    HijackPromptBarContext,
    guidance_cursor_for_prompt,
)
from sase.ace.tui.actions.agent_durable import submit_agent_recovery
from sase.ace.tui.models.agent import Agent, AgentType


def _agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/project.sase",
        status="HIJACKED",
        start_time=datetime(2026, 11, 3, 10, 0, 0),
        workspace_num=4,
        workspace_dir="/tmp/project_4",
        raw_suffix="20261103100000",
        agent_name="sase-demo.1",
        llm_provider="claude",
        model="opus",
        hijack_id="h-123",
        hijack_record={
            "hijack_id": "h-123",
            "agent_name": "sase-demo.1",
            "revision": 4,
            "state": "held",
            "workspace_num": 4,
            "workspace_dir": "/tmp/project_4",
            "provider": "claude",
            "model": "opus",
            "effort": "high",
        },
    )


def _record() -> dict[str, Any]:
    return {
        "hijack_id": "h-123",
        "agent_name": "sase-demo.1",
        "revision": 4,
        "state": "held",
        "workspace_num": 4,
        "workspace_dir": "/tmp/project_4",
        "cl_name": "feature",
        "project_file": "/tmp/project.sase",
    }


class _App:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.submissions: list[dict[str, Any]] = []
        self.mounted: list[Any] = []
        self.unmounted_submit = 0
        self.unmounted_cancel = 0
        self.saved_cancelled: list[str] = []
        self.refreshed = 0
        self._agents_with_children = [_agent()]
        self._hijack_prompt_context: HijackPromptBarContext | None = None
        self._prompt_context: Any = object()
        self._prompt_session: Any = None

    def _submit_durable_proc(self, *args: Any, **kwargs: Any) -> object:
        self.submissions.append({"args": args, **kwargs})
        return object()

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def mount(self, bar: Any) -> None:
        self.mounted.append(bar)

    def _unmount_prompt_bar(self) -> str:
        self.unmounted_cancel += 1
        return ""

    def _unmount_prompt_bar_after_submit(self) -> None:
        self.unmounted_submit += 1

    def _save_text_as_cancelled(self, text: str) -> str:
        self.saved_cancelled.append(text)
        return text

    def _discard_prompt_bar_spare(self) -> None:
        pass

    def _refresh_agents_display(self, **_kwargs: Any) -> None:
        self.refreshed += 1

    def _get_selected_agent(self) -> Agent:
        return self._agents_with_children[0]


def _hijack_app(action: str) -> _App:
    app = _App()
    app._hijack_prompt_context = HijackPromptBarContext(
        action=action,
        hijack_id="h-123",
        expected_revision=4,
        agent_name="sase-demo.1",
        cl_name="feature",
        project_file="/tmp/project.sase",
        display_name="Recover sase-demo.1",
        session_id=None,
    )
    return app


def test_guidance_cursor_with_fork_line() -> None:
    text = "%model:claude/opus@high\n#fork:sase-demo.1\n\n**Hijack continuation.**\n"
    assert guidance_cursor_for_prompt(text) == (2, 0)


def test_guidance_cursor_without_fork_line() -> None:
    text = "%model:claude/opus@high\n\n**Hijack continuation.**\n"
    assert guidance_cursor_for_prompt(text) == (1, 0)


def test_instruct_submit_runs_continue_with_edited_prompt() -> None:
    app = _hijack_app("continue")
    assert hijack_bar.handle_hijack_prompt_submitted(app, "%model:x\nDo it") is True

    [submission] = app.submissions
    assert submission["request"]["action"] == "continue"
    assert submission["request"]["prompt"] == "%model:x\nDo it"
    assert submission["request"]["expected_hijack_id"] == "h-123"
    assert app.unmounted_submit == 1
    assert app._hijack_prompt_context is None


def test_edit_submit_runs_restart_with_edited_prompt() -> None:
    app = _hijack_app("restart")
    assert hijack_bar.handle_hijack_prompt_submitted(app, "edited task") is True

    [submission] = app.submissions
    assert submission["request"]["action"] == "restart"
    assert submission["request"]["prompt"] == "edited task"


def test_submit_without_context_is_not_handled() -> None:
    app = _App()
    assert hijack_bar.handle_hijack_prompt_submitted(app, "hello") is False
    assert app.submissions == []


def test_edit_mount_releases_nothing_before_submit(monkeypatch: Any) -> None:
    app = _App()
    agent = app._agents_with_children[0]
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._entry_relaunch.prepare_kill_edit_agent_prompt",
        lambda *_args, **_kwargs: "raw prompt",
    )
    # Narrow harness has no run_worker; the resolver runs synchronously.
    hijack_bar.open_hijack_edit_bar(app, agent, _record())

    assert len(app.mounted) == 1
    assert app.submissions == []
    assert app.unmounted_cancel == 1  # old bar detached, nothing dismissed
    context = hijack_bar.get_hijack_prompt_context(app)
    assert context is not None and context.action == "restart"
    bar = app.mounted[0]
    assert bar._initial_value == "raw prompt"


def test_edit_snapshot_failure_stashes_prompt_and_keeps_hold(
    monkeypatch: Any,
) -> None:
    app = _hijack_app("restart")
    agent = app._agents_with_children[0]
    agent.hijack_overlay = "recovering"

    captured: dict[str, Any] = {}

    def _fake_submit(_app: Any, **kwargs: Any) -> bool:
        captured["on_complete"] = kwargs["on_complete"]
        return True

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_durable.submit_agent_recovery",
        _fake_submit,
    )
    assert hijack_bar.handle_hijack_prompt_submitted(app, "edited task") is True

    completion = SimpleNamespace(success=False, message="snapshot failed", payload={})
    captured["on_complete"](completion)

    assert app.saved_cancelled == ["edited task"]
    assert agent.hijack_overlay is None
    # The failed Edit keeps the ledger record so the row stays HIJACKED.
    assert agent.hijack_record is not None


def test_instruct_mount_prefills_continuation_with_guidance_cursor(
    monkeypatch: Any,
) -> None:
    app = _App()
    agent = app._agents_with_children[0]
    prompt = "%model:claude/opus@high\n#fork:sase-demo.1\n\n**Hijack continuation.**\n"
    monkeypatch.setattr(
        "sase.agent.hijack.preview.build_hijack_continuation_prompt",
        lambda *_args, **_kwargs: SimpleNamespace(prompt=prompt),
    )
    hijack_bar.open_hijack_instruct_bar(app, agent, _record())

    assert len(app.mounted) == 1
    assert app.submissions == []
    bar = app.mounted[0]
    assert bar._initial_value == prompt
    assert bar._initial_cursor == (2, 0)
    context = hijack_bar.get_hijack_prompt_context(app)
    assert context is not None and context.action == "continue"


def test_cancel_clears_context_without_recovery_proc() -> None:
    app = _hijack_app("continue")
    hijack_bar.clear_hijack_prompt_context(app)
    assert hijack_bar.get_hijack_prompt_context(app) is None
    assert app.submissions == []


def test_recovery_submit_carries_prompt_payload() -> None:
    app = _App()
    submit_agent_recovery(
        app,
        name="sase-demo.1",
        hijack_id="h-123",
        expected_revision=4,
        action="continue",
        prompt="%model:claude/opus@xhigh\nDo it",
        cl_name="feature",
        project_file="/tmp/project.sase",
        display_name="Recover sase-demo.1",
    )
    [submission] = app.submissions
    assert submission["request"]["prompt"] == "%model:claude/opus@xhigh\nDo it"
