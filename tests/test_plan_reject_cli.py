"""Tests for ``sase plan reject`` CLI rejection behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.time import get_timezone
from sase.main.plan_reject_handler import _reject_plan_from_cli
from sase.notifications.models import Notification
from sase.notifications.store import append_notification, load_notifications
from sase.plan_approval_actions import PlanApprovalActionError

_LIVE_AGENT_TS = "20260613120000"
_LIVE_AGENT_PID = 4242


def _response_dir(root: Path, name: str = "plan_approval") -> Path:
    path = root / "agent" / name
    path.mkdir(parents=True)
    (path / "plan_request.json").write_text("{}", encoding="utf-8")
    return path


def _plan_file(root: Path, name: str = "plan.md") -> Path:
    path = root / name
    path.write_text("# Plan\n", encoding="utf-8")
    return path


def _append_plan_notification(
    notification_id: str,
    plan_file: Path,
    response_dir: Path,
    *,
    agent_cl_name: str = "demo-cl",
    agent_name: str = "planner",
    agent_timestamp: str | None = _LIVE_AGENT_TS,
) -> None:
    action_data = {
        "response_dir": str(response_dir),
        "agent_cl_name": agent_cl_name,
        "agent_name": agent_name,
    }
    if agent_timestamp:
        action_data["agent_timestamp"] = agent_timestamp
    append_notification(
        Notification(
            id=notification_id,
            timestamp=datetime.now(get_timezone()).isoformat(),
            sender="plan",
            files=[str(plan_file)],
            action="PlanApproval",
            action_data=action_data,
        )
    )


def _live_agent(*, pid: int | None = _LIVE_AGENT_PID) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-cl",
        project_file="/tmp/demo-project.sase",
        status="PLAN",
        start_time=None,
        raw_suffix=_LIVE_AGENT_TS,
        agent_name="planner",
        workspace_dir="/work/demo-project",
        pid=pid,
    )


@dataclass(frozen=True)
class _FakeKillResult:
    success: bool = True
    status: str = "killed"
    error: str | None = None


@pytest.fixture(autouse=True)
def _visible_plan_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the lone pending plan resolvable from `sase plan list` visibility."""
    monkeypatch.setattr(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        lambda notifications: (_live_agent(),),
    )


def _patch_cleanup_agent_load(
    monkeypatch: pytest.MonkeyPatch, agents: tuple[Agent, ...]
) -> None:
    """Patch the agent loaders the durable reject cleanup consults."""
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader.load_live_plan_agents",
        lambda: list(agents),
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader.load_live_plan_agents_for_timestamps",
        lambda timestamps: [],
    )


def _patch_user_kill(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Capture request_user_kill calls without signalling a real process."""
    calls: list[dict[str, object]] = []

    def _fake_request_user_kill(pid: int, **kwargs: object) -> _FakeKillResult:
        calls.append({"pid": pid, **kwargs})
        return _FakeKillResult()

    monkeypatch.setattr(
        "sase.agent.user_kill.request_user_kill", _fake_request_user_kill
    )
    return calls


def test_reject_by_unique_prefix_writes_reject_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    (response_dir.parent / "agent_meta.json").write_text(
        json.dumps({"name": "planner"}),
        encoding="utf-8",
    )
    _append_plan_notification("abcdef12-plan", plan, response_dir)
    agent = _live_agent()
    _patch_cleanup_agent_load(monkeypatch, (agent,))
    kill_calls = _patch_user_kill(monkeypatch)

    result = _reject_plan_from_cli(selector="abcdef12")

    assert result.action_result.notification_id == "abcdef12-plan"
    assert result.action_result.response_json == {"action": "reject"}
    assert json.loads((response_dir / "plan_response.json").read_text()) == {
        "action": "reject"
    }
    # Rejection never writes approval metadata.
    meta = json.loads((response_dir.parent / "agent_meta.json").read_text())
    assert "plan_approved" not in meta
    assert "plan_action" not in meta
    # Notification dismissed.
    [notification] = load_notifications(include_dismissed=True)
    assert notification.dismissed is True
    # Matching live plan agent user-killed and dismissed.
    assert kill_calls and kill_calls[0]["pid"] == _LIVE_AGENT_PID
    assert result.cleanup.agent_found is True
    assert result.cleanup.killed is True
    assert result.cleanup.dismissed_identities == frozenset({agent.identity})


def test_reject_persists_dismissed_agent_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.dismissed_agents import load_dismissed_agents

    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    _append_plan_notification("abcdef12-plan", plan, response_dir)
    agent = _live_agent()
    _patch_cleanup_agent_load(monkeypatch, (agent,))
    _patch_user_kill(monkeypatch)

    _reject_plan_from_cli(selector="abcdef12")

    assert agent.identity in load_dismissed_agents()


def test_reject_omitted_selector_succeeds_with_one_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    _append_plan_notification("abcdef12-plan", plan, response_dir)
    _patch_cleanup_agent_load(monkeypatch, (_live_agent(),))
    _patch_user_kill(monkeypatch)

    result = _reject_plan_from_cli(selector=None)

    assert result.action_result.notification_id == "abcdef12-plan"
    assert (response_dir / "plan_response.json").is_file()


def test_reject_omitted_selector_errors_with_zero_or_multiple(
    tmp_path: Path,
) -> None:
    with pytest.raises(PlanApprovalActionError) as no_pending:
        _reject_plan_from_cli(selector=None)
    assert no_pending.value.code == "missing_selector"
    assert "no pending plan proposals" in str(no_pending.value)

    first_response_dir = _response_dir(tmp_path, "first")
    second_response_dir = _response_dir(tmp_path, "second")
    first_plan = _plan_file(tmp_path, "first.md")
    second_plan = _plan_file(tmp_path, "second.md")
    _append_plan_notification("abcdef12-plan", first_plan, first_response_dir)
    _append_plan_notification("12345678-plan", second_plan, second_response_dir)

    with pytest.raises(PlanApprovalActionError) as multiple_pending:
        _reject_plan_from_cli(selector=None)
    assert multiple_pending.value.code == "missing_selector"
    assert "multiple pending plan proposals" in str(multiple_pending.value)


def test_reject_duplicate_response_conflicts_without_overwrite(
    tmp_path: Path,
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    response_path = response_dir / "plan_response.json"
    response_path.write_text('{"action":"approve"}\n', encoding="utf-8")
    _append_plan_notification("abcdef12-plan", plan, response_dir)

    with pytest.raises(PlanApprovalActionError) as exc_info:
        _reject_plan_from_cli(selector="abcdef12")

    assert exc_info.value.code == "conflict_already_handled"
    assert response_path.read_text(encoding="utf-8") == '{"action":"approve"}\n'


def test_reject_missing_response_dir_is_actionable(tmp_path: Path) -> None:
    missing_response_dir = tmp_path / "missing"
    plan = _plan_file(tmp_path)
    _append_plan_notification("abcdef12-plan", plan, missing_response_dir)

    with pytest.raises(PlanApprovalActionError) as exc_info:
        _reject_plan_from_cli(selector="abcdef12")

    assert exc_info.value.code == "invalid_request"
    assert "response_dir is missing" in str(exc_info.value)


def test_reject_without_matching_agent_warns_but_writes_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    _append_plan_notification("abcdef12-plan", plan, response_dir)
    # The plan is visible (resolvable) but no live agent row matches it.
    _patch_cleanup_agent_load(monkeypatch, ())
    kill_calls = _patch_user_kill(monkeypatch)

    result = _reject_plan_from_cli(selector="abcdef12")

    assert json.loads((response_dir / "plan_response.json").read_text()) == {
        "action": "reject"
    }
    assert result.cleanup.agent_found is False
    assert result.cleanup.killed is False
    assert result.cleanup.warning
    assert not kill_calls


def test_cli_and_tui_share_durable_kill_helpers() -> None:
    """CLI rejection reuses the TUI's durable transaction and identity helpers."""
    from sase.ace.tui.actions.agents import _kill_identity, _killing
    from sase.ace.tui.actions.agents import _plan_reject_cleanup as cli_cleanup

    assert (
        cli_cleanup.persist_single_kill_transaction
        is _killing._persist_single_kill_transaction
    )
    assert (
        cli_cleanup.collect_planned_kill_identities
        is _kill_identity.collect_planned_kill_identities
    )
