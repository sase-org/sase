from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_runner_lifecycle import (
    RunnerShutdownContext,
    RunnerShutdownDeps,
    RunnerShutdownState,
    finalize_runner_shutdown,
    _should_hold_workspace,
)
from sase.running_field import ClaimResult


def _state(**overrides: object) -> RunnerShutdownState:
    state = RunnerShutdownState(
        success=False,
        duration="1s",
        workspace_num=17,
        workspace_dir="/tmp/workspace-17",
        current_artifacts_dir="/tmp/artifacts",
        running_marker_path=None,
        agent_name="worker",
        agent_model="model",
        agent_llm_provider="provider",
        agent_hidden=False,
        saved_path=None,
        diff_path=None,
        markdown_pdf_paths=[],
        markdown_source_count=0,
        image_paths=[],
        video_paths=[],
        step_output=None,
        exec_outcome="",
        error_summary="RuntimeError: boom",
        error_traceback_str=None,
        suppress_completion_notification=False,
        runtime="1s",
    )
    return replace(state, **overrides)


@pytest.mark.parametrize(
    ("overrides", "was_killed", "auto_dismiss", "steps_hidden", "expected"),
    [
        ({}, False, False, False, True),
        (
            {"success": True, "exec_outcome": "completed"},
            False,
            False,
            False,
            False,
        ),
        ({"exec_outcome": "killed"}, False, False, False, False),
        ({"exec_outcome": "failed_retried"}, False, False, False, False),
        ({"exec_outcome": "plan_rejected"}, False, False, False, False),
        ({"exec_outcome": "plan_committed"}, False, False, False, False),
        ({"exec_outcome": "epic_approved"}, False, False, False, False),
        ({"exec_outcome": "epic_launch_failed"}, False, False, False, False),
        ({}, True, False, False, False),
        ({}, False, True, False, False),
        ({}, False, False, True, False),
        ({"suppress_completion_notification": True}, False, False, False, False),
        ({"agent_hidden": True}, False, False, False, True),
    ],
)
def test_should_hold_workspace_matches_terminal_failed_rows(
    overrides: dict[str, object],
    was_killed: bool,
    auto_dismiss: bool,
    steps_hidden: bool,
    expected: bool,
) -> None:
    assert (
        _should_hold_workspace(
            _state(**overrides),
            was_killed=was_killed,
            auto_dismiss=auto_dismiss,
            steps_hidden=steps_hidden,
        )
        is expected
    )


def test_finalize_holds_failed_workspace_and_surfaces_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SASE_AGENT_AUTO_DISMISS", raising=False)
    output_path = tmp_path / "output.log"
    output_path.write_text("run output", encoding="utf-8")
    context = RunnerShutdownContext(
        project_file="/tmp/project.sase",
        workflow_name="ace(run)-260712_120000",
        cl_name="feature",
        artifacts_timestamp="20260712120000",
        artifacts_dir=str(tmp_path),
        output_path=str(output_path),
        submitted_xprompt="do work",
        prompt="do work",
        is_home_mode=False,
    )
    write_error_report = MagicMock(return_value="/tmp/error_report.md")
    send_notification = MagicMock()
    deps = RunnerShutdownDeps(
        update_artifact_index=MagicMock(),
        was_killed=MagicMock(return_value=False),
        all_steps_hidden=MagicMock(return_value=False),
        write_error_report=write_error_report,
        send_completion_notification=send_notification,
        auto_dismiss_completed_agent=MagicMock(),
    )

    with (
        patch(
            "sase.running_field.hold_workspace_claim",
            return_value=ClaimResult(success=True),
        ) as hold,
        patch("sase.running_field.release_workspace") as release,
    ):
        finalize_runner_shutdown(context=context, state=_state(), deps=deps)

    hold.assert_called_once_with(
        "/tmp/project.sase",
        17,
        "ace(run)-260712_120000",
        "feature",
        "20260712120000",
    )
    release.assert_not_called()
    assert write_error_report.call_args.kwargs["held_workspace_num"] == 17
    assert send_notification.call_args.kwargs["held_workspace_num"] == 17
    assert (
        send_notification.call_args.kwargs["held_workspace_dir"] == "/tmp/workspace-17"
    )
    assert "Workspace #17 held (visible failed run)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("steps_hidden", "suppress_completion_notification"),
    [
        (True, False),
        (False, True),
    ],
)
def test_finalize_releases_failed_workspace_without_visible_notification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    steps_hidden: bool,
    suppress_completion_notification: bool,
) -> None:
    monkeypatch.delenv("SASE_AGENT_AUTO_DISMISS", raising=False)
    context = RunnerShutdownContext(
        project_file="/tmp/project.sase",
        workflow_name="run",
        cl_name="feature",
        artifacts_timestamp="20260712120000",
        artifacts_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        submitted_xprompt="do work",
        prompt="do work",
        is_home_mode=False,
    )
    all_steps_hidden = MagicMock(return_value=steps_hidden)
    send_notification = MagicMock()
    deps = RunnerShutdownDeps(
        update_artifact_index=MagicMock(),
        was_killed=MagicMock(return_value=False),
        all_steps_hidden=all_steps_hidden,
        write_error_report=MagicMock(),
        send_completion_notification=send_notification,
        auto_dismiss_completed_agent=MagicMock(),
    )

    with (
        patch("sase.running_field.hold_workspace_claim") as hold,
        patch("sase.running_field.release_workspace") as release,
    ):
        finalize_runner_shutdown(
            context=context,
            state=_state(
                error_summary=None,
                suppress_completion_notification=suppress_completion_notification,
            ),
            deps=deps,
        )

    hold.assert_not_called()
    release.assert_called_once_with("/tmp/project.sase", 17, "run", "feature")
    all_steps_hidden.assert_called_once_with("/tmp/artifacts")
    send_notification.assert_not_called()


def test_finalize_releases_failed_retry_parent(tmp_path: Path) -> None:
    context = RunnerShutdownContext(
        project_file="/tmp/project.sase",
        workflow_name="run",
        cl_name="feature",
        artifacts_timestamp="20260712120000",
        artifacts_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        submitted_xprompt="do work",
        prompt="do work",
        is_home_mode=False,
    )
    deps = RunnerShutdownDeps(
        update_artifact_index=MagicMock(),
        was_killed=MagicMock(return_value=False),
        all_steps_hidden=MagicMock(return_value=True),
        write_error_report=MagicMock(),
        send_completion_notification=MagicMock(),
        auto_dismiss_completed_agent=MagicMock(),
    )
    with (
        patch("sase.running_field.hold_workspace_claim") as hold,
        patch("sase.running_field.release_workspace") as release,
    ):
        finalize_runner_shutdown(
            context=context,
            state=_state(
                exec_outcome="failed_retried",
                error_summary=None,
            ),
            deps=deps,
        )

    hold.assert_not_called()
    release.assert_called_once_with("/tmp/project.sase", 17, "run", "feature")


def test_finalize_releases_held_prelaunch_bead_claim(tmp_path: Path) -> None:
    output_path = tmp_path / "output.log"
    context = RunnerShutdownContext(
        project_file="/tmp/project.sase",
        workflow_name="run",
        cl_name="feature",
        artifacts_timestamp="20260712120000",
        artifacts_dir=str(tmp_path),
        output_path=str(output_path),
        submitted_xprompt="do work",
        prompt="do work",
        is_home_mode=True,
    )
    deps = RunnerShutdownDeps(
        update_artifact_index=MagicMock(),
        was_killed=MagicMock(return_value=True),
        all_steps_hidden=MagicMock(return_value=True),
        write_error_report=MagicMock(),
        send_completion_notification=MagicMock(),
        auto_dismiss_completed_agent=MagicMock(),
    )

    with patch(
        "sase.bead.claims.release_bead_claim_for_agent",
        return_value=True,
    ) as release:
        finalize_runner_shutdown(
            context=context,
            state=_state(
                error_summary=None,
                suppress_completion_notification=True,
                held_bead_claim_id="sase-1.2",
                held_bead_claim_agent="sase-1.2",
                held_bead_claim_project="sase",
            ),
            deps=deps,
        )

    release.assert_called_once_with(
        project_name="sase",
        bead_id="sase-1.2",
        agent_name="sase-1.2",
    )


@pytest.mark.parametrize("marker", [".sase_plan_pending", ".sase_questions_pending"])
def test_finalize_preserves_held_bead_claim_for_pending_handoff(
    tmp_path: Path, marker: str
) -> None:
    (tmp_path / marker).touch()
    context = RunnerShutdownContext(
        project_file="/tmp/project.sase",
        workflow_name="run",
        cl_name="feature",
        artifacts_timestamp="20260712120000",
        artifacts_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        submitted_xprompt="do work",
        prompt="do work",
        is_home_mode=True,
    )
    deps = RunnerShutdownDeps(
        update_artifact_index=MagicMock(),
        was_killed=MagicMock(return_value=False),
        all_steps_hidden=MagicMock(return_value=True),
        write_error_report=MagicMock(),
        send_completion_notification=MagicMock(),
        auto_dismiss_completed_agent=MagicMock(),
    )

    with patch("sase.bead.claims.release_bead_claim_for_agent") as release:
        finalize_runner_shutdown(
            context=context,
            state=_state(
                error_summary=None,
                suppress_completion_notification=True,
                held_bead_claim_id="sase-1.2",
                held_bead_claim_agent="sase-1.2",
                held_bead_claim_project="sase",
            ),
            deps=deps,
        )

    release.assert_not_called()
