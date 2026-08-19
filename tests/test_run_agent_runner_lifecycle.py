"""Workspace hold/release behavior of ``finalize_runner_shutdown``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_runner_lifecycle import (
    finalize_runner_shutdown,
    _should_hold_workspace,
)
from sase.running_field import ClaimResult, WorkspaceClaim
from sase.workspace_provider.occupant import (
    new_occupant_record,
    read_occupant_record,
    write_occupant_record,
)
from tests._run_agent_runner_lifecycle_helpers import (
    make_context,
    make_deps,
    make_state,
)


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
            make_state(**overrides),
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
    (tmp_path / "output.log").write_text("run output", encoding="utf-8")
    context = make_context(tmp_path, workflow_name="ace(run)-260712_120000")
    write_error_report = MagicMock(return_value="/tmp/error_report.md")
    send_notification = MagicMock()
    deps = make_deps(
        all_steps_hidden=MagicMock(return_value=False),
        write_error_report=write_error_report,
        send_completion_notification=send_notification,
    )

    with (
        patch(
            "sase.running_field.hold_workspace_claim",
            return_value=ClaimResult(success=True),
        ) as hold,
        patch("sase.running_field.release_workspace") as release,
    ):
        finalize_runner_shutdown(context=context, state=make_state(), deps=deps)

    hold.assert_called_once_with(
        "/tmp/project.sase",
        17,
        "ace(run)-260712_120000",
        "feature",
        "20260712120000",
        caller_tag="agent-finalize",
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
    context = make_context(tmp_path)
    all_steps_hidden = MagicMock(return_value=steps_hidden)
    send_notification = MagicMock()
    deps = make_deps(
        all_steps_hidden=all_steps_hidden,
        send_completion_notification=send_notification,
    )

    with (
        patch("sase.running_field.hold_workspace_claim") as hold,
        patch("sase.running_field.release_workspace") as release,
    ):
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                error_summary=None,
                suppress_completion_notification=suppress_completion_notification,
            ),
            deps=deps,
        )

    hold.assert_not_called()
    release.assert_called_once_with(
        "/tmp/project.sase", 17, "run", "feature", caller_tag="agent-finalize"
    )
    all_steps_hidden.assert_called_once_with("/tmp/artifacts")
    send_notification.assert_not_called()


def test_finalize_clears_occupant_record_on_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A released workspace must no longer name this agent as occupant."""
    monkeypatch.delenv("SASE_AGENT_AUTO_DISMISS", raising=False)
    workspace_dir = tmp_path / "workspace-17"
    workspace_dir.mkdir()
    write_occupant_record(
        str(workspace_dir),
        new_occupant_record(pid=1234, workflow="run", project="sase", workspace_num=17),
    )
    context = make_context(tmp_path)
    deps = make_deps()

    with (
        patch("sase.running_field.hold_workspace_claim"),
        patch("sase.running_field.release_workspace"),
    ):
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                workspace_dir=str(workspace_dir),
                error_summary=None,
                suppress_completion_notification=False,
            ),
            deps=deps,
        )

    assert read_occupant_record(str(workspace_dir)) is None


def test_finalize_releases_failed_retry_parent(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    deps = make_deps()

    with (
        patch("sase.running_field.hold_workspace_claim") as hold,
        patch("sase.running_field.release_workspace") as release,
    ):
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                exec_outcome="failed_retried",
                error_summary=None,
            ),
            deps=deps,
        )

    hold.assert_not_called()
    release.assert_called_once_with(
        "/tmp/project.sase", 17, "run", "feature", caller_tag="agent-finalize"
    )


def test_finalize_does_not_touch_workspace_for_monitored_handoff(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    deps = make_deps()

    with (
        patch(
            "sase.running_field.get_claimed_workspaces",
            return_value=[
                WorkspaceClaim(
                    workspace_num=17,
                    workflow="ace-monitor",
                    cl_name="feature",
                    pid=12345,
                )
            ],
        ),
        patch("sase.ace.hooks.processes.is_process_running", return_value=True),
        patch("sase.running_field.hold_workspace_claim") as hold,
        patch("sase.running_field.release_workspace") as release,
    ):
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                success=True,
                exec_outcome="monitored",
                error_summary=None,
            ),
            deps=deps,
        )

    hold.assert_not_called()
    release.assert_not_called()


def test_finalize_releases_monitored_workspace_without_live_monitor_claim(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)
    deps = make_deps()

    with (
        patch("sase.running_field.get_claimed_workspaces", return_value=[]),
        patch("sase.running_field.hold_workspace_claim") as hold,
        patch("sase.running_field.release_workspace") as release,
    ):
        finalize_runner_shutdown(
            context=context,
            state=make_state(
                success=True,
                exec_outcome="monitored",
                error_summary=None,
            ),
            deps=deps,
        )

    hold.assert_not_called()
    release.assert_called_once_with(
        "/tmp/project.sase", 17, "run", "feature", caller_tag="agent-finalize"
    )
