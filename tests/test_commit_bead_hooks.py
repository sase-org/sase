"""Tests for CommitWorkflow bead hooks."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workflows.commit.bead_hooks import (
    close_task_bead_after_commit,
    handle_beads,
)

_CONFIG_TARGET = "sase.workflows.commit.command_hooks.load_merged_config"
_BEAD_REPO_ROOT_TARGET = "sase.workflows.commit.bead_hooks.get_repo_root"


@pytest.fixture(autouse=True)
def _no_commit_hooks():  # type: ignore[no-untyped-def]
    """Prevent commit hooks and SASE_PLAN from running in tests."""
    with (
        patch(
            _CONFIG_TARGET,
            return_value={"commit_hooks": {"before": "", "after": ""}},
        ),
        patch.dict("os.environ", {"SASE_PLAN": ""}, clear=False),
    ):
        yield


_SYNC_RESULT = subprocess.CompletedProcess(
    ["sase", "bead", "sync"], 0, stdout=b"", stderr=b""
)
_CLOSE_RESULT = subprocess.CompletedProcess(
    ["sase", "bead", "close"], 0, stdout=b"", stderr=b""
)


def _show_result(
    status: str, issue_type: str = "task"
) -> "subprocess.CompletedProcess[bytes]":
    """Return a fake ``sase bead show --format json`` result."""
    detail = json.dumps(
        {"issue": {"id": "B-123", "status": status, "issue_type": issue_type}}
    ).encode()
    return subprocess.CompletedProcess(
        ["sase", "bead", "show", "B-123", "--format", "json"],
        0,
        stdout=detail,
        stderr=b"",
    )


class TestHandleBeads:
    """Verify bead hook remains best-effort in test/CI environments."""

    def test_missing_sase_cli_is_non_fatal_and_message_is_unchanged(
        self, tmp_path: Path
    ) -> None:
        payload = {"message": "Fix bug", "bead_id": "B-123"}
        with patch(
            "sase.workflows.commit.bead_hooks.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            handle_beads(payload, str(tmp_path))

        assert payload["message"] == "Fix bug"

    def test_in_progress_task_bead_is_armed_without_a_pre_commit_reminder(
        self, tmp_path: Path
    ) -> None:
        payload = {"message": "Fix bug", "bead_id": "B-123"}
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                side_effect=[_show_result("in_progress"), _SYNC_RESULT],
            ) as run,
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            handle_beads(payload, str(tmp_path))

        assert [call.args[0] for call in run.call_args_list] == [
            ["sase", "bead", "show", "B-123", "--format", "json"],
            ["sase", "bead", "sync"],
        ]
        print_status.assert_not_called()

    def test_autoclose_closes_in_progress_task_in_primary_repo(
        self, tmp_path: Path
    ) -> None:
        payload = {"message": "fix: bug\n\nBody", "bead_id": "B-123"}
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                side_effect=[_show_result("in_progress"), _CLOSE_RESULT],
            ) as run,
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch(
                "sase.workflows.commit.bead_hooks._resolve_short_head",
                return_value="abc123",
            ),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert close_task_bead_after_commit(
                payload, str(tmp_path), method="create_commit"
            )

        assert [call.args[0][:3] for call in run.call_args_list] == [
            ["sase", "bead", "show"],
            ["sase", "bead", "close"],
        ]
        close_args = run.call_args_list[1].args[0]
        assert close_args[:6] == [
            "sase",
            "bead",
            "close",
            "B-123",
            "--resolution",
            "done",
        ]
        note = close_args[close_args.index("--note") + 1]
        assert "Auto-closed by `sase commit` after create_commit landed abc123" in note
        assert '("fix: bug")' in note
        assert "No verification is implied by this note" in note
        message, level = print_status.call_args.args
        assert level == "success"
        assert "Auto-closed task bead B-123" in message

    @pytest.mark.parametrize("issue_type", ["phase", "plan"])
    def test_non_task_beads_are_not_auto_closed(
        self, tmp_path: Path, issue_type: str
    ) -> None:
        payload = {"message": "Fix bug", "bead_id": "B-123"}
        with patch(
            "sase.workflows.commit.bead_hooks.subprocess.run",
            side_effect=[_show_result("in_progress", issue_type)],
        ) as run:
            assert not close_task_bead_after_commit(
                payload, str(tmp_path), method="create_commit"
            )

        assert len(run.call_args_list) == 1

    @pytest.mark.parametrize(
        "status", ["open", "ready", "claimed", "snoozed", "closed"]
    )
    def test_task_bead_statuses_other_than_in_progress_are_not_auto_closed(
        self, tmp_path: Path, status: str
    ) -> None:
        payload = {"message": "Fix bug", "bead_id": "B-123"}
        with patch(
            "sase.workflows.commit.bead_hooks.subprocess.run",
            side_effect=[_show_result(status)],
        ) as run:
            assert not close_task_bead_after_commit(
                payload, str(tmp_path), method="create_commit"
            )

        assert len(run.call_args_list) == 1

    def test_opt_out_does_not_auto_close(self, tmp_path: Path) -> None:
        payload = {
            "message": "Fix bug",
            "bead_id": "B-123",
            "do_not_close_bead": True,
        }
        with patch(
            "sase.workflows.commit.bead_hooks.subprocess.run",
            side_effect=[_show_result("in_progress")],
        ) as run:
            assert not close_task_bead_after_commit(
                payload, str(tmp_path), method="create_commit"
            )

        assert len(run.call_args_list) == 1

    def test_sidecar_commit_does_not_close_the_workspace_bead(
        self, tmp_path: Path
    ) -> None:
        """A plans/linked-repo commit cannot signal the deliverable is done."""
        sidecar = tmp_path / "sase--plans"
        sidecar.mkdir()
        payload = {"message": "docs: mark plan done", "bead_id": "B-123"}
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                side_effect=[_show_result("in_progress"), _SYNC_RESULT],
            ) as run,
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(sidecar)),
            patch.dict("os.environ", {"SASE_SDD_PLANS_DIR": str(sidecar)}),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            handle_beads(payload, str(sidecar))

        assert not any(
            call.args[0][:3] == ["sase", "bead", "close"] for call in run.call_args_list
        )
        message, level = print_status.call_args.args
        assert level == "warning"
        assert "linked repository or SDD sidecar" in message

    def test_linked_repo_commit_does_not_auto_close(self, tmp_path: Path) -> None:
        linked = tmp_path / "linked"
        linked.mkdir()
        payload = {"message": "Fix bug", "bead_id": "B-123"}
        linked_json = json.dumps(
            [{"name": "tooling", "workspace_dir": str(linked), "primary_dir": ""}]
        )

        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                side_effect=[_show_result("in_progress")],
            ) as run,
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(linked)),
            patch.dict("os.environ", {"SASE_LINKED_REPOS_JSON": linked_json}),
        ):
            assert not close_task_bead_after_commit(
                payload, str(linked), method="create_commit"
            )

        assert len(run.call_args_list) == 1

    def test_sdd_plans_repo_commit_does_not_auto_close(self, tmp_path: Path) -> None:
        sidecar = tmp_path / "plans"
        sidecar.mkdir()
        payload = {"message": "Fix bug", "bead_id": "B-123"}

        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                side_effect=[_show_result("in_progress")],
            ) as run,
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(sidecar)),
            patch.dict("os.environ", {"SASE_SDD_PLANS_DIR": str(sidecar)}),
        ):
            assert not close_task_bead_after_commit(
                payload, str(sidecar), method="create_commit"
            )

        assert len(run.call_args_list) == 1

    def test_non_zero_close_exit_warns_without_raising(self, tmp_path: Path) -> None:
        payload = {"message": "fix: bug", "bead_id": "B-123"}
        close_failed = subprocess.CompletedProcess(
            ["sase", "bead", "close"], 1, stdout=b"", stderr=b"blocked by child"
        )
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                side_effect=[_show_result("in_progress"), close_failed],
            ),
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch(
                "sase.workflows.commit.bead_hooks._resolve_short_head",
                return_value="abc123",
            ),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert not close_task_bead_after_commit(
                payload, str(tmp_path), method="create_commit"
            )

        message, level = print_status.call_args.args
        assert level == "warning"
        assert "Auto-close failed for task bead B-123" in message
        assert "blocked by child" in message

    def test_already_closed_bead_is_left_alone_without_a_reminder(
        self, tmp_path: Path
    ) -> None:
        payload = {"message": "Fix bug", "bead_id": "B-123"}
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                side_effect=[_show_result("closed"), _SYNC_RESULT],
            ),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            handle_beads(payload, str(tmp_path))

        print_status.assert_not_called()

    @pytest.mark.parametrize(
        "show",
        [
            subprocess.CompletedProcess(["sase"], 1, stdout=b"", stderr=b"boom"),
            subprocess.CompletedProcess(["sase"], 0, stdout=b"not json", stderr=b""),
            subprocess.CompletedProcess(["sase"], 0, stdout=b"{}", stderr=b""),
        ],
        ids=["failed", "unparseable", "no-issue"],
    )
    def test_unresolvable_bead_status_warns_and_still_syncs(
        self, tmp_path: Path, show: "subprocess.CompletedProcess[bytes]"
    ) -> None:
        payload = {"message": "Fix bug", "bead_id": "B-123"}
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                side_effect=[show, _SYNC_RESULT],
            ) as run,
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            handle_beads(payload, str(tmp_path))

        message, level = print_status.call_args.args
        assert level == "warning"
        assert "could not be read" in message
        assert run.call_args_list[-1].args[0] == ["sase", "bead", "sync"]

    def test_bead_sync_runs_when_bead_dir_exists(self, tmp_path: Path) -> None:
        (tmp_path / "sdd/beads").mkdir(parents=True)
        payload = {"message": "Fix bug"}
        with patch(
            "sase.workflows.commit.bead_hooks.subprocess.run",
        ) as mock_run:
            handle_beads(payload, str(tmp_path))

        mock_run.assert_called_once_with(
            ["sase", "bead", "sync"],
            cwd=str(tmp_path),
            capture_output=True,
            check=False,
        )

    def test_bead_sync_runs_when_split_sidecar_exists(self, tmp_path: Path) -> None:
        (tmp_path / "sase/repos/beads").mkdir(parents=True)
        payload = {"message": "Fix bug"}
        with patch(
            "sase.workflows.commit.bead_hooks.subprocess.run",
        ) as mock_run:
            handle_beads(payload, str(tmp_path))

        mock_run.assert_called_once_with(
            ["sase", "bead", "sync"],
            cwd=str(tmp_path),
            capture_output=True,
            check=False,
        )
