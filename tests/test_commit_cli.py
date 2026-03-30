"""Tests for the commit CLI: flag parsing -> payload dict -> workflow construction."""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.main.parser_commands import register_commit_parser


def _parse_commit_args(argv: list[str]) -> argparse.Namespace:
    """Parse argv through the commit subparser."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    register_commit_parser(subparsers)
    return parser.parse_args(["commit", *argv])


def _write_msg(tmp_path: Path, content: str) -> str:
    """Write content to a temp message file and return its path."""
    path = tmp_path / "message.md"
    path.write_text(content)
    return str(path)


def _run_handler(
    argv: list[str], env: dict[str, str] | None = None
) -> tuple[dict, str]:
    """Run handle_commit_command and return (payload, method) passed to CommitWorkflow."""
    args = _parse_commit_args(argv)
    mock_workflow = MagicMock()
    mock_workflow.run.return_value = True

    with (
        patch("sase.main.cl_handler.CommitWorkflow", return_value=mock_workflow) as cls,
        patch.dict("os.environ", env or {}, clear=False),
        pytest.raises(SystemExit) as exc_info,
    ):
        from sase.main.cl_handler import handle_commit_command

        handle_commit_command(args)

    assert exc_info.value.code == 0
    call_kwargs = cls.call_args.kwargs
    return call_kwargs["payload"], call_kwargs["method"]


class TestCommitCLI:
    """Test commit CLI flag -> payload mapping."""

    def test_basic_commit(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "fix: bug")
        payload, method = _run_handler(["create", "-F", msg_file, "-f", "a.py"])
        assert payload == {"message": "fix: bug", "files": ["a.py"]}
        assert method == "create_commit"

    def test_commit_message_string(self) -> None:
        payload, method = _run_handler(
            ["create", "-m", "feat: string msg", "-f", "a.py"]
        )
        assert payload == {"message": "feat: string msg", "files": ["a.py"]}
        assert method == "create_commit"

    def test_project_flag(self, tmp_path: Path) -> None:
        # Create a sibling project directory
        project_dir = tmp_path.parent / "my-project"
        project_dir.mkdir(exist_ok=True)
        msg_file = _write_msg(tmp_path, "msg")

        # Mock os.chdir to verify it's called with the correct path
        with (
            patch("os.chdir") as mock_chdir,
            patch("os.getcwd", return_value=str(tmp_path)),
        ):
            _run_handler(["create", "-F", msg_file, "-p", "my-project"])
            mock_chdir.assert_called_once()
            args, _ = mock_chdir.call_args
            assert args[0].endswith("my-project")

    def test_multiple_files(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(
            ["create", "-F", msg_file, "-f", "a.py", "-f", "b.py"]
        )
        assert payload["files"] == ["a.py", "b.py"]

    def test_no_files_stages_all(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["create", "-F", msg_file])
        assert payload["files"] == []

    def test_bead_id(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["create", "-F", msg_file, "--bead-id", "sase-42"])
        assert payload["bead_id"] == "sase-42"

    def test_pr_name(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, method = _run_handler(
            ["pull-request", "-F", msg_file, "--name", "feat-branch"]
        )
        assert payload["name"] == "feat-branch"
        assert method == "create_pull_request"

    def test_checkout_target(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(
            [
                "pull-request",
                "-F",
                msg_file,
                "--name",
                "feat",
                "--checkout-target",
                "origin/main",
            ]
        )
        assert payload["checkout_target"] == "origin/main"

    def test_checkout_target_default_omitted(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        payload, _ = _run_handler(["create", "-F", msg_file])
        assert "checkout_target" not in payload

    def test_method_flag(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        _, method = _run_handler(
            ["create", "-F", msg_file, "--method", "create_proposal"]
        )
        assert method == "create_proposal"

    def test_method_from_env(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        _, method = _run_handler(
            ["create", "-F", msg_file], env={"SASE_COMMIT_METHOD": "create_proposal"}
        )
        assert method == "create_proposal"

    def test_default_method(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "msg")
        _, method = _run_handler(["create", "-F", msg_file], env={})
        assert method == "create_commit"

    def test_message_file_not_found(self) -> None:
        args = _parse_commit_args(["create", "-F", "/nonexistent/message.md"])
        with pytest.raises(SystemExit) as exc_info:
            from sase.main.cl_handler import handle_commit_command

            handle_commit_command(args)
        assert exc_info.value.code == 1

    def test_message_file_deleted_after_read(self, tmp_path: Path) -> None:
        msg_file = _write_msg(tmp_path, "feat: something")
        assert Path(msg_file).exists()
        _run_handler(["create", "-F", msg_file])
        assert not Path(msg_file).exists()

    def test_message_file_multiline(self, tmp_path: Path) -> None:
        content = "## Summary\n\n- Added feature X\n- Fixed bug Y\n\n## Test plan\n\n- Unit tests added"
        msg_file = _write_msg(tmp_path, content)
        payload, _ = _run_handler(["create", "-F", msg_file])
        assert payload["message"] == content
