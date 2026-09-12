"""Tests for CommitWorkflow bead hooks."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workflows.commit.bead_hooks import (
    BeadActionPolicyError,
    close_assigned_bead_after_commit,
    handle_beads,
    validate_bead_action_before_commit,
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
    """Verify bead sync remains best-effort after policy preflight."""

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

    def test_assigned_bead_syncs_without_reading_or_closing(
        self, tmp_path: Path
    ) -> None:
        payload = {"message": "Fix bug", "bead_id": "B-123"}
        with patch(
            "sase.workflows.commit.bead_hooks.subprocess.run",
            return_value=_SYNC_RESULT,
        ) as run:
            handle_beads(payload, str(tmp_path))

        run.assert_called_once_with(
            ["sase", "bead", "sync"],
            cwd=str(tmp_path),
            capture_output=True,
            check=False,
        )

    def test_bead_sync_runs_when_bead_dir_exists(self, tmp_path: Path) -> None:
        (tmp_path / "sdd/beads").mkdir(parents=True)
        payload = {"message": "Fix bug"}
        with patch(
            "sase.workflows.commit.bead_hooks.subprocess.run",
            return_value=_SYNC_RESULT,
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
            return_value=_SYNC_RESULT,
        ) as mock_run:
            handle_beads(payload, str(tmp_path))

        mock_run.assert_called_once_with(
            ["sase", "bead", "sync"],
            cwd=str(tmp_path),
            capture_output=True,
            check=False,
        )


class TestBeadActionPreflight:
    """Verify explicit bead-action decisions gate assigned-bead commits."""

    def test_assigned_bead_requires_explicit_action(self, tmp_path: Path) -> None:
        payload = {"message": "fix: bug", "bead_id": "B-123"}
        with (
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch.dict("os.environ", {"SASE_ACTIVE_PROJECT_DIR": str(tmp_path)}),
            patch("sase.workflows.commit.bead_hooks.subprocess.run") as run,
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert not validate_bead_action_before_commit(
                payload,
                str(tmp_path),
                method="create_commit",
            )

        run.assert_not_called()
        message, level = print_status.call_args.args
        assert level == "error"
        assert "bead_action is required" in message

    def test_keep_allows_commit_without_status_lookup(self, tmp_path: Path) -> None:
        payload = {"message": "fix: bug", "bead_id": "B-123", "bead_action": "keep"}
        with (
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch.dict("os.environ", {"SASE_ACTIVE_PROJECT_DIR": str(tmp_path)}),
            patch("sase.workflows.commit.bead_hooks.subprocess.run") as run,
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert validate_bead_action_before_commit(
                payload,
                str(tmp_path),
                method="create_commit",
            )

        run.assert_not_called()
        message, level = print_status.call_args.args
        assert level == "info"
        assert "left unchanged" in message

    def test_close_preflight_requires_in_progress_bead(self, tmp_path: Path) -> None:
        payload = {"message": "fix: bug", "bead_id": "B-123", "bead_action": "close"}
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                return_value=_show_result("in_progress"),
            ) as run,
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch.dict("os.environ", {"SASE_ACTIVE_PROJECT_DIR": str(tmp_path)}),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert validate_bead_action_before_commit(
                payload,
                str(tmp_path),
                method="create_commit",
            )

        run.assert_called_once()
        assert run.call_args.args[0][:3] == ["sase", "bead", "show"]
        message, level = print_status.call_args.args
        assert level == "info"
        assert "will be closed" in message

    @pytest.mark.parametrize("status", ["open", "ready", "claimed", "snoozed"])
    def test_close_preflight_rejects_non_in_progress_status(
        self, tmp_path: Path, status: str
    ) -> None:
        payload = {"message": "fix: bug", "bead_id": "B-123", "bead_action": "close"}
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                return_value=_show_result(status),
            ),
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch.dict("os.environ", {"SASE_ACTIVE_PROJECT_DIR": str(tmp_path)}),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert not validate_bead_action_before_commit(
                payload,
                str(tmp_path),
                method="create_commit",
            )

        message, level = print_status.call_args.args
        assert level == "error"
        assert "close requires the assigned bead" in message

    def test_legacy_do_not_close_field_is_rejected(self, tmp_path: Path) -> None:
        payload = {
            "message": "fix: bug",
            "bead_id": "B-123",
            "do_not_close_bead": True,
        }
        with (
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch.dict("os.environ", {"SASE_ACTIVE_PROJECT_DIR": str(tmp_path)}),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert not validate_bead_action_before_commit(
                payload,
                str(tmp_path),
                method="create_commit",
            )

        message, level = print_status.call_args.args
        assert level == "error"
        assert "--do-not-close-bead is no longer accepted" in message


class TestCloseAssignedBeadAfterCommit:
    """Verify post-commit close is explicit, primary-only, and strict when asked."""

    @pytest.mark.parametrize("issue_type", ["task", "phase", "plan"])
    def test_explicit_close_closes_in_progress_assigned_bead_in_primary_repo(
        self, tmp_path: Path, issue_type: str
    ) -> None:
        payload = {
            "message": "fix: bug\n\nBody",
            "bead_id": "B-123",
            "bead_action": "close",
        }
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                side_effect=[_show_result("in_progress", issue_type), _CLOSE_RESULT],
            ) as run,
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch.dict("os.environ", {"SASE_ACTIVE_PROJECT_DIR": str(tmp_path)}),
            patch(
                "sase.workflows.commit.bead_hooks._resolve_short_head",
                return_value="abc123",
            ),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert close_assigned_bead_after_commit(
                payload,
                str(tmp_path),
                method="create_commit",
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
        assert "Closed by explicit `sase stitch create -B close`" in note
        assert '("fix: bug")' in note
        assert "verifying the bead scope" in note
        message, level = print_status.call_args.args
        assert level == "success"
        assert "Closed assigned bead B-123" in message

    def test_keep_does_not_close(self, tmp_path: Path) -> None:
        payload = {"message": "fix: bug", "bead_id": "B-123", "bead_action": "keep"}
        with (
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch.dict("os.environ", {"SASE_ACTIVE_PROJECT_DIR": str(tmp_path)}),
            patch("sase.workflows.commit.bead_hooks.subprocess.run") as run,
        ):
            assert not close_assigned_bead_after_commit(
                payload,
                str(tmp_path),
                method="create_commit",
            )

        run.assert_not_called()

    def test_already_closed_bead_is_idempotent(self, tmp_path: Path) -> None:
        payload = {"message": "fix: bug", "bead_id": "B-123", "bead_action": "close"}
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                return_value=_show_result("closed"),
            ) as run,
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch.dict("os.environ", {"SASE_ACTIVE_PROJECT_DIR": str(tmp_path)}),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert close_assigned_bead_after_commit(
                payload,
                str(tmp_path),
                method="create_commit",
            )

        run.assert_called_once()
        message, level = print_status.call_args.args
        assert level == "info"
        assert "already satisfied" in message

    def test_non_zero_close_exit_warns_without_raising(self, tmp_path: Path) -> None:
        payload = {"message": "fix: bug", "bead_id": "B-123", "bead_action": "close"}
        close_failed = subprocess.CompletedProcess(
            ["sase", "bead", "close"], 1, stdout=b"", stderr=b"blocked by child"
        )
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                side_effect=[_show_result("in_progress"), close_failed],
            ),
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch.dict("os.environ", {"SASE_ACTIVE_PROJECT_DIR": str(tmp_path)}),
            patch(
                "sase.workflows.commit.bead_hooks._resolve_short_head",
                return_value="abc123",
            ),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert not close_assigned_bead_after_commit(
                payload,
                str(tmp_path),
                method="create_commit",
            )

        message, level = print_status.call_args.args
        assert level == "warning"
        assert "Explicit close failed for bead B-123" in message
        assert "blocked by child" in message

    def test_strict_close_failure_raises(self, tmp_path: Path) -> None:
        payload = {"message": "fix: bug", "bead_id": "B-123", "bead_action": "close"}
        close_failed = subprocess.CompletedProcess(
            ["sase", "bead", "close"], 1, stdout=b"", stderr=b"blocked by child"
        )
        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                side_effect=[_show_result("in_progress"), close_failed],
            ),
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch.dict("os.environ", {"SASE_ACTIVE_PROJECT_DIR": str(tmp_path)}),
            patch(
                "sase.workflows.commit.bead_hooks._resolve_short_head",
                return_value="abc123",
            ),
        ):
            with pytest.raises(BeadActionPolicyError, match="Explicit close failed"):
                close_assigned_bead_after_commit(
                    payload,
                    str(tmp_path),
                    method="create_commit",
                    strict=True,
                )

    def test_linked_repo_commit_does_not_close(self, tmp_path: Path) -> None:
        linked = tmp_path / "linked"
        linked.mkdir()
        payload = {"message": "fix: bug", "bead_id": "B-123", "bead_action": "close"}
        linked_json = json.dumps(
            [{"name": "tooling", "workspace_dir": str(linked), "primary_dir": ""}]
        )

        with (
            patch(
                "sase.workflows.commit.bead_hooks.subprocess.run",
                return_value=_show_result("in_progress"),
            ),
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(linked)),
            patch.dict("os.environ", {"SASE_LINKED_REPOS_JSON": linked_json}),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert not close_assigned_bead_after_commit(
                payload,
                str(linked),
                method="create_commit",
            )

        message, level = print_status.call_args.args
        assert level == "warning"
        assert "only the owning primary repository" in message

    def test_close_without_assigned_bead_is_refused(self, tmp_path: Path) -> None:
        payload = {"message": "fix: bug", "bead_action": "close"}
        with (
            patch(_BEAD_REPO_ROOT_TARGET, return_value=str(tmp_path)),
            patch.dict("os.environ", {"SASE_ACTIVE_PROJECT_DIR": str(tmp_path)}),
            patch("sase.workflows.commit.bead_hooks.print_status") as print_status,
        ):
            assert not close_assigned_bead_after_commit(
                payload,
                str(tmp_path),
                method="create_commit",
            )

        message, level = print_status.call_args.args
        assert level == "warning"
        assert "there is no assigned bead to close" in message
