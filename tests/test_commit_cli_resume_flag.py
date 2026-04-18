"""Tests for the `sase commit --resume` CLI flag."""

import argparse
from unittest.mock import patch

import pytest

from sase.main.parser_commands import register_commit_parser
from sase.workflows.commit.workflow import RunResult


def _parse_commit_args(argv: list[str]) -> argparse.Namespace:
    """Parse argv through the commit subparser."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    register_commit_parser(subparsers)
    return parser.parse_args(["commit", *argv])


class TestResumeFlag:
    """Test the --resume flag parses and routes correctly."""

    def test_parser_exposes_resume_flag(self) -> None:
        args_short = _parse_commit_args(["-r"])
        assert args_short.resume is True

        args_long = _parse_commit_args(["--resume"])
        assert args_long.resume is True

        args_none = _parse_commit_args([])
        assert args_none.resume is False

    def test_resume_flag_invokes_workflow_resume(self) -> None:
        args = _parse_commit_args(["--resume"])
        with (
            patch(
                "sase.workflows.commit.workflow.CommitWorkflow.resume",
                return_value=RunResult.OK,
            ) as mock_resume,
            pytest.raises(SystemExit) as exc_info,
        ):
            from sase.main.cl_handler import handle_commit_command

            handle_commit_command(args)

        assert exc_info.value.code == 0
        mock_resume.assert_called_once_with()

    def test_resume_flag_maps_conflict_to_exit_2(self) -> None:
        args = _parse_commit_args(["--resume"])
        with (
            patch(
                "sase.workflows.commit.workflow.CommitWorkflow.resume",
                return_value=RunResult.CONFLICT,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            from sase.main.cl_handler import handle_commit_command

            handle_commit_command(args)

        assert exc_info.value.code == 2

    def test_resume_flag_maps_failed_to_exit_1(self) -> None:
        args = _parse_commit_args(["--resume"])
        with (
            patch(
                "sase.workflows.commit.workflow.CommitWorkflow.resume",
                return_value=RunResult.FAILED,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            from sase.main.cl_handler import handle_commit_command

            handle_commit_command(args)

        assert exc_info.value.code == 1

    def test_resume_flag_skips_payload_assembly(self) -> None:
        """The resume branch must not construct a CommitWorkflow instance."""
        args = _parse_commit_args(["--resume"])
        init_err = AssertionError("CommitWorkflow.__init__ should not be called")
        with (
            patch(
                "sase.workflows.commit.workflow.CommitWorkflow.resume",
                return_value=RunResult.OK,
            ),
            patch(
                "sase.workflows.commit.workflow.CommitWorkflow.__init__",
                side_effect=init_err,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            from sase.main.cl_handler import handle_commit_command

            handle_commit_command(args)

        assert exc_info.value.code == 0
