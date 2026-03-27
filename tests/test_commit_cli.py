"""Tests for the commit CLI: flag parsing -> payload dict -> workflow construction."""

import argparse
from unittest.mock import MagicMock, patch

import pytest

from sase.main.parser_commands import register_commit_parser


def _parse_commit_args(argv: list[str]) -> argparse.Namespace:
    """Parse argv through the commit subparser."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    register_commit_parser(subparsers)
    return parser.parse_args(["commit", *argv])


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

    def test_basic_commit(self) -> None:
        payload, method = _run_handler(["-m", "fix: bug", "-f", "a.py"])
        assert payload == {"message": "fix: bug", "files": ["a.py"]}
        assert method == "create_commit"

    def test_multiple_files(self) -> None:
        payload, _ = _run_handler(["-m", "msg", "-f", "a.py", "-f", "b.py"])
        assert payload["files"] == ["a.py", "b.py"]

    def test_no_files_stages_all(self) -> None:
        payload, _ = _run_handler(["-m", "msg"])
        assert payload["files"] == []

    def test_bead_id(self) -> None:
        payload, _ = _run_handler(["-m", "msg", "--bead-id", "sase-42"])
        assert payload["bead_id"] == "sase-42"

    def test_pr_name(self) -> None:
        payload, _ = _run_handler(["-m", "msg", "--name", "feat-branch"])
        assert payload["name"] == "feat-branch"

    def test_checkout_target(self) -> None:
        payload, _ = _run_handler(
            ["-m", "msg", "--name", "feat", "--checkout-target", "origin/main"]
        )
        assert payload["checkout_target"] == "origin/main"

    def test_checkout_target_default_omitted(self) -> None:
        payload, _ = _run_handler(["-m", "msg"])
        assert "checkout_target" not in payload

    def test_note(self) -> None:
        payload, _ = _run_handler(["-m", "msg", "--note", "my note"])
        assert payload["note"] == "my note"

    def test_method_flag(self) -> None:
        _, method = _run_handler(["-m", "msg", "--method", "create_proposal"])
        assert method == "create_proposal"

    def test_method_from_env(self) -> None:
        _, method = _run_handler(
            ["-m", "msg"], env={"SASE_COMMIT_METHOD": "create_proposal"}
        )
        assert method == "create_proposal"

    def test_default_method(self) -> None:
        _, method = _run_handler(["-m", "msg"], env={})
        assert method == "create_commit"
