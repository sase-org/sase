"""Agent Hijack recovery-panel choices and durable actions."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents import (
    _hijack_recovery_panel as panel,
    _hijack_recovery_panel_impl as panel_helpers,
    _hijack_recovery_preview as preview_helpers,
)
from sase.ace.tui.actions.agent_durable import submit_agent_recovery
from sase.ace.tui.models.agent import Agent, AgentType


def _agent(*, state: str = "held", expired: bool = False) -> Agent:
    agent = Agent(
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
        hijack_expired=expired,
        hijack_record={
            "hijack_id": "h-123",
            "agent_name": "sase-demo.1",
            "artifacts_dir": "/tmp/agent-artifacts",
            "revision": 4,
            "state": state,
            "workspace_num": 4,
            "workspace_dir": "/tmp/project_4",
            "model_alias": "large",
            "provider": "claude",
            "model": "opus",
            "effort": "high",
            "run_duration_seconds": 2820,
            "last_tool": "Bash just check",
            "last_tool_age_seconds": 1320,
            "repo_diffs": [
                {
                    "repo": "/tmp/project_4",
                    "files_changed": 5,
                    "insertions": 212,
                    "deletions": 31,
                }
            ],
            "snapshots": [{"repo": "/tmp/project_4", "reference": "snapshot-123"}],
        },
    )
    return agent


class _App:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.submissions: list[dict[str, Any]] = []

    def _resolve_agent_cl_name(self, _agent: Agent) -> str:
        return "feature"

    def _find_agent_enter_patch_summary(self, _patch_name: str) -> None:
        return None

    def _submit_durable_proc(self, *args: Any, **kwargs: Any) -> object:
        self.submissions.append({"args": args, **kwargs})
        return object()

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))


def test_panel_choices_are_grouped_and_patch_is_last() -> None:
    agent = _agent()
    app = _App()

    choices = panel_helpers._initial_choices(app, agent, agent.hijack_record or {})

    assert [choice.hotkey for choice in choices] == [
        "u",
        "c",
        "i",
        "r",
        "e",
        "v",
        "t",
        "d",
        "p",
    ]
    assert [choice.section for choice in choices] == [
        "hijack_keep",
        "hijack_keep",
        "hijack_keep",
        "hijack_fresh",
        "hijack_fresh",
        "hijack_other",
        "hijack_other",
        "hijack_other",
        "patch",
    ]
    assert all(choice.pending for choice in choices if choice.hotkey in {"u", "c", "r"})
    assert choices[-1].result == "patch:feature"
    assert choices[-1].action_target == "feature"


def test_expired_panel_has_release_actions_without_keep_work_primary() -> None:
    agent = _agent(state="expired", expired=True)
    choices = panel_helpers._initial_choices(_App(), agent, agent.hijack_record or {})

    hotkeys = {choice.hotkey for choice in choices}
    assert hotkeys == {"r", "e", "v", "t", "d", "p"}
    assert all(choice.section != "hijack_keep" for choice in choices)
    assert panel_helpers._title_badge(agent, agent.hijack_record or {}).endswith(
        "released"
    )


def test_preview_updates_target_and_disabled_reasons() -> None:
    agent = _agent()
    choices = panel_helpers._initial_choices(_App(), agent, agent.hijack_record or {})
    actions = {
        "escalate": SimpleNamespace(
            label="Switch",
            detail="already @xlarge",
            target="codex/gpt-6.1-sol@xhigh",
            available=False,
            reason="no different model available",
        ),
        "continue": SimpleNamespace(
            label="Continue",
            detail="same model",
            target="claude/opus@high",
            available=True,
            reason=None,
        ),
    }
    preview = SimpleNamespace(state="held", action=lambda name: actions.get(name))

    updated = preview_helpers._apply_preview(choices, preview)

    assert updated[0].glyph == "↔"
    assert updated[0].disabled_reason == "no different model available"
    assert updated[1].action_target == "claude/opus@high"
    assert not updated[1].pending


def test_cached_preview_is_keyed_by_hijack_revision(monkeypatch: Any) -> None:
    record = {"hijack_id": "h-cache", "revision": 9}
    preview = object()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sase.agent.hijack.preview.hijack_recovery_preview",
        lambda current: calls.append(current) or preview,
    )

    assert preview_helpers._cached_preview_for_record(record) is preview
    assert preview_helpers._cached_preview_for_record(record) is preview
    assert len(calls) == 1


def test_recovery_action_submission_pins_revision_and_model() -> None:
    app = _App()
    submit_agent_recovery(
        app,
        name="sase-demo.1",
        hijack_id="h-123",
        expected_revision=4,
        action="escalate",
        model="claude/opus@xhigh",
        cl_name="feature",
        project_file="/tmp/project.sase",
        display_name="Recover sase-demo.1",
    )

    [submission] = app.submissions
    assert submission["operation"] == "agent.persist-recover"
    assert submission["request"] == {
        "name": "sase-demo.1",
        "expected_hijack_id": "h-123",
        "expected_revision": 4,
        "action": "escalate",
        "model": "claude/opus@xhigh",
    }
    assert submission["concurrency_keys"] == ("agent-hijack-recovery:h-123",)


def test_x_dismiss_uses_snapshot_gated_recovery_proc(
    monkeypatch: Any,
) -> None:
    agent = _agent()
    app = _App()
    app._agents_with_children = [agent]
    app._refresh_agents_display = lambda **_kwargs: None
    submitted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._roster_generation.notify_roster_status_mutation",
        lambda _app: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_durable.submit_agent_recovery",
        lambda _app, **kwargs: submitted.append(kwargs) or True,
    )

    assert panel.dismiss_hijacked_agent(app, agent)
    assert agent.hijack_overlay == "recovering"
    assert submitted[0]["action"] == "dismiss"
    assert submitted[0]["expected_revision"] == 4
    assert submitted[0]["hijack_id"] == "h-123"
