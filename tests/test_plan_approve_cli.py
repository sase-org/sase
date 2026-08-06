"""Tests for ``sase plan approve`` CLI approval behavior."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.time import get_timezone
from sase.main.plan_approve_handler import (
    _approve_plan_from_cli,
    get_tmux_prefix,
    handle_plan_approve_command,
)
from sase.notifications.models import Notification
from sase.notifications.store import append_notification, load_notifications
from sase.plan_approval_actions import (
    PlanApprovalActionError,
    PlanApprovalActionResult,
    PlanApprovalValidationError,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN
from tests.sdd_policy_helpers import patched_sdd_policy

_LIVE_AGENT_TS = "20260613120000"


def _response_dir(root: Path, name: str = "plan_approval") -> Path:
    path = root / "agent" / name
    path.mkdir(parents=True)
    (path / "plan_request.json").write_text("{}", encoding="utf-8")
    return path


def _plan_file(root: Path, name: str = "plan.md") -> Path:
    path = root / name
    path.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    return path


def _append_plan_notification(
    notification_id: str,
    plan_file: Path,
    response_dir: Path,
    *,
    project_dir: Path | None = None,
    agent_project_file: Path | None = None,
    agent_cl_name: str = "demo-cl",
    agent_name: str = "planner",
    agent_timestamp: str | None = _LIVE_AGENT_TS,
) -> None:
    action_data = {
        "response_dir": str(response_dir),
        "agent_cl_name": agent_cl_name,
        "agent_name": agent_name,
    }
    if project_dir is not None:
        action_data["project_dir"] = str(project_dir)
    if agent_project_file is not None:
        action_data["agent_project_file"] = str(agent_project_file)
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


def _live_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-cl",
        project_file="/tmp/demo-project.sase",
        status="PLAN",
        start_time=None,
        raw_suffix=_LIVE_AGENT_TS,
        agent_name="planner",
        workspace_dir="/work/demo-project",
    )


def test_tmux_prefix_uses_runtime_neutral_project_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.env_contracts import PROVIDER_PROJECT_DIR_ENV_VARS

    for env_name in PROVIDER_PROJECT_DIR_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(tmp_path / "codex-project"))
    monkeypatch.delenv("TMUX_PANE", raising=False)

    assert get_tmux_prefix() == "[codex-project]"


@pytest.fixture(autouse=True)
def _visible_plan_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        lambda notifications: (_live_agent(),),
    )


@pytest.mark.parametrize(
    ("kind", "expected_json", "expected_meta_action"),
    [
        (
            "approve",
            {"action": "approve", "commit_plan": False, "run_coder": True},
            "approve",
        ),
        (
            "tale",
            {"action": "approve", "commit_plan": True, "run_coder": True},
            "tale",
        ),
        (
            "commit",
            {"action": "approve", "commit_plan": True, "run_coder": False},
            "commit",
        ),
    ],
)
def test_plan_approve_by_unique_prefix_writes_protocol_json_and_meta(
    tmp_path: Path,
    kind: str,
    expected_json: dict[str, object],
    expected_meta_action: str,
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    (response_dir.parent / "agent_meta.json").write_text(
        json.dumps({"name": "planner"}),
        encoding="utf-8",
    )
    _append_plan_notification("abcdef12-plan", plan, response_dir)

    result = _approve_plan_from_cli(selector="abcdef12", kind=kind)

    assert result.notification_id == "abcdef12-plan"
    assert result.response_json == expected_json
    assert (
        json.loads((response_dir / "plan_response.json").read_text()) == expected_json
    )
    meta = json.loads((response_dir.parent / "agent_meta.json").read_text())
    assert meta["plan_approved"] is True
    assert meta["plan_action"] == expected_meta_action


def test_plan_approve_omitted_kind_uses_authored_epic_tier(tmp_path: Path) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _append_plan_notification(
        "abcdef12-plan",
        plan,
        response_dir,
        project_dir=workspace,
    )

    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_cwd",
            return_value=workspace,
        ),
        patch(
            "sase.bead.epic_launch.submit_epic_launch_task",
            return_value=SimpleNamespace(task_id="task-omitted"),
        ),
    ):
        result = _approve_plan_from_cli(selector="abcdef12", kind=None)

    assert result.response_json == {
        "action": "epic",
        "commit_plan": True,
        "run_coder": True,
        "epic_launch_owner": "host",
    }
    assert result.epic_launch_task_id == "task-omitted"


def test_cli_epic_approval_submits_detached_after_claiming_ownership(
    tmp_path: Path,
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent_project_file = tmp_path / "projects" / "canonical" / "canonical.sase"
    _append_plan_notification(
        "abcdef12-plan",
        plan,
        response_dir,
        project_dir=workspace,
        agent_project_file=agent_project_file,
    )

    def submit_detached(*_args: object, **_kwargs: object) -> object:
        response = json.loads((response_dir / "plan_response.json").read_text())
        assert response["epic_launch_owner"] == "host"
        return SimpleNamespace(task_id="task-cli")

    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_cwd",
            return_value=workspace,
        ) as resolve_cwd,
        patch(
            "sase.bead.epic_launch.submit_epic_launch_task",
            side_effect=submit_detached,
        ) as launch,
    ):
        result = _approve_plan_from_cli(selector="abcdef12", kind="epic")

    assert result.response_json["epic_launch_owner"] == "host"
    assert result.epic_launch_task_id == "task-cli"
    assert resolve_cwd.call_count == 2
    resolve_cwd.assert_called_with(
        str(workspace),
        agent_project_file=str(agent_project_file),
    )
    launch.assert_called_once()
    assert launch.call_args.args == (str(plan),)
    assert launch.call_args.kwargs["cwd"] == workspace
    assert launch.call_args.kwargs["origin"] == "cli"


def test_failed_epic_gate_leaves_proposal_pending_and_retryable(
    tmp_path: Path,
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _append_plan_notification(
        "abcdef12-plan",
        plan,
        response_dir,
        project_dir=workspace,
    )

    with pytest.raises(PlanApprovalValidationError) as exc_info:
        _approve_plan_from_cli(selector="abcdef12", kind="epic")

    assert exc_info.value.code == "plan_validation_failed"
    assert "required-missing" in str(exc_info.value)
    assert not (response_dir / "plan_response.json").exists()
    assert (response_dir / "plan_request.json").is_file()
    [notification] = load_notifications(include_dismissed=True)
    assert notification.dismissed is False

    plan.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_cwd",
            return_value=workspace,
        ),
        patch(
            "sase.bead.epic_launch.submit_epic_launch_task",
            return_value=SimpleNamespace(task_id="task-retry"),
        ),
    ):
        result = _approve_plan_from_cli(selector="abcdef12", kind="epic")

    assert result.response_json["action"] == "epic"
    assert (response_dir / "plan_response.json").is_file()
    [notification] = load_notifications(include_dismissed=True)
    assert notification.dismissed is True


def test_plan_approve_cli_renders_validation_schema_and_exits_one(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    _append_plan_notification("abcdef12-plan", plan, response_dir)
    args = argparse.Namespace(
        selector="abcdef12",
        kind="epic",
        prompt=None,
        model=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_plan_approve_command(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Expected epic frontmatter schema" in captured.err
    assert "Minimal valid epic plan" in captured.err
    assert "Validation failed" in captured.err
    assert not (response_dir / "plan_response.json").exists()


def test_plan_approve_cli_prints_detached_task_follow_hint(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(
        selector="abcdef12",
        kind="epic",
        prompt=None,
        model=None,
    )
    result = PlanApprovalActionResult(
        notification_id="abcdef12-plan",
        response_file="plan_response.json",
        response_path=tmp_path / "plan_response.json",
        response_json={"action": "epic"},
        message="Epic approved",
        epic_launch_task_id="task-123",
    )

    with (
        patch(
            "sase.main.plan_approve_handler._approve_plan_from_cli",
            return_value=result,
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_plan_approve_command(args)

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "Detached task task-123" in output
    assert "sase task show task-123 --follow" in output


def test_epic_authored_plan_can_be_downgraded_to_tale(tmp_path: Path) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    _append_plan_notification("abcdef12-plan", plan, response_dir)

    result = _approve_plan_from_cli(selector="abcdef12", kind="tale")

    assert result.response_json == {
        "action": "approve",
        "commit_plan": True,
        "run_coder": True,
    }


def test_plan_approve_marks_shared_action_handled(tmp_path: Path) -> None:
    """CLI/mobile approval flips the shared action to already_handled."""
    from sase.notifications.pending_actions import read_pending_action_store

    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    _append_plan_notification("abcdef12-plan", plan, response_dir)

    _approve_plan_from_cli(selector="abcdef12", kind="approve")

    entry = read_pending_action_store()["actions"]["abcdef12"]
    assert entry["state"] == "already_handled"
    assert entry["handled_source"] == "plan_response"
    assert entry["handled_action"] == "approve"


def test_plan_approve_can_include_coder_prompt_and_model(tmp_path: Path) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    _append_plan_notification("abcdef12-plan", plan, response_dir)

    # This fixture's action data names no project, so archiving cannot run;
    # its failure report is out of scope for the notification assertion below.
    with patch("sase._plan_archive_approval.report_plan_archive_failure"):
        result = _approve_plan_from_cli(
            selector="abcdef12",
            kind="approve",
            coder_prompt="Focus on tests",
            coder_model="worker",
        )

    assert result.response_json == {
        "action": "approve",
        "commit_plan": False,
        "run_coder": True,
        "coder_prompt": "Focus on tests",
        "coder_model": "worker",
    }
    [notification] = load_notifications(include_dismissed=True)
    assert notification.dismissed is True


def test_plan_approve_omitted_selector_succeeds_with_one_pending_plan(
    tmp_path: Path,
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    _append_plan_notification("abcdef12-plan", plan, response_dir)

    result = _approve_plan_from_cli(selector=None, kind="approve")

    assert result.notification_id == "abcdef12-plan"
    assert (response_dir / "plan_response.json").is_file()


def test_plan_approve_omitted_selector_ignores_orphaned_pending_plan(
    tmp_path: Path,
) -> None:
    visible_response_dir = _response_dir(tmp_path, "visible")
    orphan_response_dir = _response_dir(tmp_path, "orphan")
    visible_plan = _plan_file(tmp_path, "visible.md")
    orphan_plan = _plan_file(tmp_path, "orphan.md")
    _append_plan_notification("abcdef12-plan", visible_plan, visible_response_dir)
    _append_plan_notification(
        "12345678-plan",
        orphan_plan,
        orphan_response_dir,
        agent_name="orphan",
        agent_timestamp="20260613130000",
    )

    result = _approve_plan_from_cli(selector=None, kind="approve")

    assert result.notification_id == "abcdef12-plan"
    assert (visible_response_dir / "plan_response.json").is_file()
    assert not (orphan_response_dir / "plan_response.json").exists()


def test_plan_approve_omitted_selector_errors_with_zero_or_multiple(
    tmp_path: Path,
) -> None:
    with pytest.raises(PlanApprovalActionError) as no_pending:
        _approve_plan_from_cli(selector=None, kind="approve")
    assert no_pending.value.code == "missing_selector"
    assert "no pending plan proposals" in str(no_pending.value)

    first_response_dir = _response_dir(tmp_path, "first")
    second_response_dir = _response_dir(tmp_path, "second")
    first_plan = _plan_file(tmp_path, "first.md")
    second_plan = _plan_file(tmp_path, "second.md")
    _append_plan_notification("abcdef12-plan", first_plan, first_response_dir)
    _append_plan_notification("12345678-plan", second_plan, second_response_dir)

    with pytest.raises(PlanApprovalActionError) as multiple_pending:
        _approve_plan_from_cli(selector=None, kind="approve")
    assert multiple_pending.value.code == "missing_selector"
    assert "multiple pending plan proposals" in str(multiple_pending.value)


def test_plan_approve_duplicate_response_conflicts_without_overwrite(
    tmp_path: Path,
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = _plan_file(tmp_path)
    response_path = response_dir / "plan_response.json"
    response_path.write_text('{"action":"approve"}\n', encoding="utf-8")
    _append_plan_notification("abcdef12-plan", plan, response_dir)

    with pytest.raises(PlanApprovalActionError) as exc_info:
        _approve_plan_from_cli(selector="abcdef12", kind="approve")

    assert exc_info.value.code == "conflict_already_handled"
    assert response_path.read_text(encoding="utf-8") == '{"action":"approve"}\n'


def test_plan_approve_missing_response_dir_is_actionable(tmp_path: Path) -> None:
    missing_response_dir = tmp_path / "missing"
    plan = _plan_file(tmp_path)
    _append_plan_notification("abcdef12-plan", plan, missing_response_dir)

    with pytest.raises(PlanApprovalActionError) as exc_info:
        _approve_plan_from_cli(selector="abcdef12", kind="approve")

    assert exc_info.value.code == "invalid_request"
    assert "response_dir is missing" in str(exc_info.value)


def test_plan_approve_archives_sdd_path_and_refreshes_index(
    tmp_path: Path,
) -> None:
    response_dir = _response_dir(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = _plan_file(tmp_path)
    (response_dir.parent / "agent_meta.json").write_text(
        json.dumps({"name": "planner"}),
        encoding="utf-8",
    )
    _append_plan_notification(
        "abcdef12-plan",
        plan,
        response_dir,
        project_dir=workspace,
    )

    with (
        patch(
            "sase.running_field.get_workspace_directory", return_value=str(workspace)
        ),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.get_yyyymm", return_value="202606"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
        patch(
            "sase.plan_approval_actions.update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
    ):
        result = _approve_plan_from_cli(selector="abcdef12", kind="tale")

    saved = str(workspace / "sdd" / "plans" / "202606" / "plan.md")
    assert result.response_json["saved_plan_path"] == saved
    assert (
        json.loads((response_dir / "plan_response.json").read_text())["saved_plan_path"]
        == saved
    )
    assert Path(saved).is_file()
    assert "tier: tale" in Path(saved).read_text(encoding="utf-8")
    meta = json.loads((response_dir.parent / "agent_meta.json").read_text())
    assert meta["plan_action"] == "tale"
    ensure_sdd.assert_called_once_with(str(workspace), commit=True, push=False)
    update_index.assert_called_once_with(response_dir.parent)
