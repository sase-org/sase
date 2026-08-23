"""Tests for `sase stitch create`: flag parsing -> payload dict -> workflow construction."""

import argparse
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.main.stitch_handler import handle_stitch_command
from sase.workflows.commit.workflow import RunResult
from tests.main.parser_cli_helpers import parse_sase_args


def _parse_stitch_create_args(argv: list[str]) -> argparse.Namespace:
    """Parse argv through the canonical ``sase stitch create`` parser."""
    return parse_sase_args(["stitch", "create", *argv])


def _write_msg(tmp_path: Path, content: str) -> str:
    """Write content to a temp message file and return its path."""
    path = tmp_path / "message.md"
    path.write_text(content)
    return str(path)


def _run_handler(
    argv: list[str], env: dict[str, str] | None = None
) -> tuple[dict, str]:
    """Run stitch create and return (payload, method) passed to CommitWorkflow."""
    args = _parse_stitch_create_args(argv)
    mock_workflow = MagicMock()
    mock_workflow.run.return_value = RunResult.OK
    requested_env = env or {}
    test_env = {"SASE_BEAD_ID": "", **requested_env}

    with patch.dict("os.environ", test_env, clear=False):
        if "SASE_COMMIT_METHOD" not in requested_env:
            os.environ.pop("SASE_COMMIT_METHOD", None)

        with (
            patch(
                "sase.main.stitch_create_handler.CommitWorkflow",
                return_value=mock_workflow,
            ) as cls,
            pytest.raises(SystemExit) as exc_info,
        ):
            handle_stitch_command(args)

    assert exc_info.value.code == 0
    call_kwargs = cls.call_args.kwargs
    return call_kwargs["payload"], call_kwargs["method"]


class TestStitchCreateCLI:
    """Test stitch-create CLI flag -> payload mapping."""

    def test_basic_commit(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "fix: bug")
        payload, method = _run_handler(["-M", msg_file])
        assert payload == {"message": "fix: bug", "files": [], "exclude": []}
        assert method == "create_commit"

    def test_only_file_flag(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file, "--only-file", "a.py"])
        assert payload["files"] == ["a.py"]

    def test_only_file_multiple(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(
            ["-M", msg_file, "--only-file", "a.py", "--only-file", "b.py"]
        )
        assert payload["files"] == ["a.py", "b.py"]

    def test_exclude_flag_multiple(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file, "-x", "a.py", "-x", "b/"])
        assert payload["exclude"] == ["a.py", "b"]

    def test_removed_file_flag_exits_1(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        with pytest.raises(SystemExit) as exc_info:
            _parse_stitch_create_args(["-M", msg_file, "-f", "a.py"])
        assert exc_info.value.code == 1

    def test_removed_file_flag_bare_exits_1(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        with pytest.raises(SystemExit) as exc_info:
            _parse_stitch_create_args(["-M", msg_file, "-f"])
        assert exc_info.value.code == 1

    def test_only_file_and_exclude_mutually_exclusive(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        args = _parse_stitch_create_args(
            ["-M", msg_file, "--only-file", "a.py", "-x", "b.py"]
        )
        with (
            patch("sase.main.stitch_create_handler.CommitWorkflow") as cls,
            patch.dict("os.environ", {"SASE_BEAD_ID": ""}, clear=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            handle_stitch_command(args)
        assert exc_info.value.code == 1
        cls.assert_not_called()

    @pytest.mark.parametrize("bad_path", ["/etc/passwd", "../outside", ":(top)a.py"])
    def test_invalid_exclude_path_exits_1(self, tmp_path: Path, bad_path: str) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        args = _parse_stitch_create_args(["-M", msg_file, "-x", bad_path])
        with (
            patch("sase.main.stitch_create_handler.CommitWorkflow") as cls,
            patch.dict("os.environ", {"SASE_BEAD_ID": ""}, clear=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            handle_stitch_command(args)
        assert exc_info.value.code == 1
        cls.assert_not_called()

    def test_no_files_stages_all(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file])
        assert payload["files"] == []
        assert payload["exclude"] == []

    @pytest.mark.parametrize("flag", ["--bead-id"])
    def test_bead_id_flag_rejected(self, tmp_path: Path, flag: str) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        with pytest.raises(SystemExit) as exc_info:
            _parse_stitch_create_args(["-M", msg_file, flag, "sase-42"])
        assert exc_info.value.code == 2

    def test_bead_id_from_env(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file], env={"SASE_BEAD_ID": "sase-42"})
        assert payload["bead_id"] == "sase-42"

    def test_bead_id_env_unset_omitted(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file])
        assert "bead_id" not in payload

    @pytest.mark.parametrize("env_value", ["", "   ", "\t\n"])
    def test_bead_id_env_blank_omitted(self, tmp_path: Path, env_value: str) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file], env={"SASE_BEAD_ID": env_value})
        assert "bead_id" not in payload

    def test_bead_id_env_stripped(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file], env={"SASE_BEAD_ID": "  sase-42  "})
        assert payload["bead_id"] == "sase-42"

    def test_pr_name(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file, "--name", "feat-branch"])
        assert payload["name"] == "feat-branch"

    def test_checkout_target(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(
            ["-M", msg_file, "--name", "feat", "--checkout-target", "origin/main"]
        )
        assert payload["checkout_target"] == "origin/main"

    def test_checkout_target_default_omitted(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file])
        assert "checkout_target" not in payload

    def test_method_flag(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        _, method = _run_handler(["-M", msg_file, "--type", "create_proposal"])
        assert method == "create_proposal"

    def test_method_from_env(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        _, method = _run_handler(
            ["-M", msg_file], env={"SASE_COMMIT_METHOD": "create_proposal"}
        )
        assert method == "create_proposal"

    def test_default_method(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        _, method = _run_handler(["-M", msg_file], env={})
        assert method == "create_commit"

    @pytest.mark.parametrize("flag", ["-b", "--bug-id"])
    def test_bug_id_flag(self, tmp_path: Path, flag: str) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file, flag, "12345"])
        assert payload["bug_id"] == "12345"

    def test_bug_id_default_omitted(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file])
        assert "bug_id" not in payload
        assert "do_not_close_bead" not in payload

    def test_do_not_close_bead_flag(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file, "-B"])
        assert payload["do_not_close_bead"] is True

    def test_do_not_close_bead_long_flag(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file, "--do-not-close-bead"])
        assert payload["do_not_close_bead"] is True

    def test_do_not_close_bead_help_mentions_assigned_in_progress_bead(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _parse_commit_args(["-h"])

        assert exc_info.value.code == 0
        assert "assigned in-progress bead" in capsys.readouterr().out

    def test_stale_uppercase_bug_id_flag_is_rejected(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        with pytest.raises(SystemExit) as exc_info:
            _parse_stitch_create_args(["-M", msg_file, "-B", "12345"])
        assert exc_info.value.code == 2

    def test_message_file_not_found(self) -> None:
        args = _parse_stitch_create_args(["-M", "/nonexistent/message.md"])
        with pytest.raises(SystemExit) as exc_info:
            handle_stitch_command(args)
        assert exc_info.value.code == 1

    def test_message_file_deleted_after_success(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "feat: something")
        assert Path(msg_file).exists()
        _run_handler(["-M", msg_file])
        assert not Path(msg_file).exists()

    @pytest.mark.parametrize(
        "result,exit_code",
        [(RunResult.FAILED, 1), (RunResult.CONFLICT, 2)],
    )
    def test_message_file_preserved_after_unsuccessful_workflow(
        self, tmp_path: Path, result: RunResult, exit_code: int
    ) -> None:
        msg_file = _write_msg(tmp_path, "feat: keep me")
        args = _parse_stitch_create_args(["-M", msg_file])
        mock_workflow = MagicMock()
        mock_workflow.run.return_value = result

        with (
            patch(
                "sase.main.stitch_create_handler.CommitWorkflow",
                return_value=mock_workflow,
            ),
            patch.dict("os.environ", {"SASE_BEAD_ID": ""}, clear=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            handle_stitch_command(args)

        assert exc_info.value.code == exit_code
        assert Path(msg_file).read_text() == "feat: keep me"

    def test_message_file_multiline(self, tmp_path: Path) -> None:
        content = "## Summary\n\n- Added feature X\n- Fixed bug Y\n\n## Test plan\n\n- Unit tests added"
        msg_file = _write_msg(tmp_path, content)
        payload, _ = _run_handler(["-M", msg_file])
        assert payload["message"] == content

    def test_inline_message(self) -> None:
        payload, method = _run_handler(["-m", "fix: inline bug", "--only-file", "a.py"])
        assert payload == {
            "message": "fix: inline bug",
            "files": ["a.py"],
            "exclude": [],
        }
        assert method == "create_commit"

    def test_inline_message_no_files(self) -> None:
        payload, _ = _run_handler(["-m", "chore: cleanup"])
        assert payload["message"] == "chore: cleanup"
        assert payload["files"] == []
        assert payload["exclude"] == []

    @pytest.mark.parametrize(
        "alias,canonical",
        [
            ("commit", "create_commit"),
            ("propose", "create_proposal"),
            ("pr", "create_pull_request"),
        ],
    )
    def test_method_alias_via_flag(
        self, tmp_path: Path, alias: str, canonical: str
    ) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        _, method = _run_handler(["-M", msg_file, "--type", alias])
        assert method == canonical

    def test_env_bead_id_with_method_alias_and_message_file(
        self, tmp_path: Path
    ) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, method = _run_handler(
            ["-M", msg_file, "--type", "pr", "--name", "feat-branch"],
            env={"SASE_BEAD_ID": "sase-42"},
        )
        assert payload["bead_id"] == "sase-42"
        assert payload["message"] == "msg"
        assert method == "create_pull_request"

    @pytest.mark.parametrize(
        "alias,canonical",
        [
            ("commit", "create_commit"),
            ("propose", "create_proposal"),
            ("pr", "create_pull_request"),
        ],
    )
    def test_method_alias_via_env(
        self, tmp_path: Path, alias: str, canonical: str
    ) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        _, method = _run_handler(["-M", msg_file], env={"SASE_COMMIT_METHOD": alias})
        assert method == canonical

    def test_parent_flag(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file, "-p", "parent_cl"])
        assert payload["parent"] == "parent_cl"

    def test_parent_default_omitted(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["-M", msg_file])
        assert "parent" not in payload

    def test_conflicting_cli_env_methods_exits_1(self, tmp_path: Path) -> None:
        """CLI --type that conflicts with SASE_COMMIT_METHOD must fail."""
        msg_file = _write_msg(tmp_path, "msg")
        args = _parse_stitch_create_args(["-M", msg_file, "--type", "commit"])
        with (
            patch("sase.main.stitch_create_handler.CommitWorkflow") as cls,
            patch.dict(
                "os.environ",
                {"SASE_COMMIT_METHOD": "create_pull_request"},
                clear=False,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            handle_stitch_command(args)

        assert exc_info.value.code == 1
        cls.assert_not_called()

    def test_conflicting_methods_allowed_with_override(self, tmp_path: Path) -> None:
        """SASE_COMMIT_METHOD_ALLOW_OVERRIDE=1 lets CLI win over env."""
        msg_file = _write_msg(tmp_path, "msg")
        _, method = _run_handler(
            ["-M", msg_file, "--type", "commit"],
            env={
                "SASE_COMMIT_METHOD": "create_pull_request",
                "SASE_COMMIT_METHOD_ALLOW_OVERRIDE": "1",
            },
        )
        assert method == "create_commit"

    def test_matching_cli_env_methods_ok(self, tmp_path: Path) -> None:
        """CLI and env agreeing on the same canonical method is fine."""
        msg_file = _write_msg(tmp_path, "msg")
        _, method = _run_handler(
            ["-M", msg_file, "--type", "pr"],
            env={"SASE_COMMIT_METHOD": "create_pull_request"},
        )
        assert method == "create_pull_request"

    def test_message_and_message_file_mutually_exclusive(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        with pytest.raises(SystemExit):
            _parse_stitch_create_args(["-m", "inline", "-M", msg_file])
