"""Tests for the launch approval parser command group."""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.main.launch_handler import handle_launch_command
from sase.main.parser import create_parser
from tests.main.parser_help_helpers import help_subcommand_rows, parser_for


def test_launch_command_group_parses_subcommands() -> None:
    """``sase launch`` resolves pending LaunchApproval requests."""
    parser = create_parser(only="launch")

    approve_args = parser.parse_args(["launch", "approve", "launch-1"])
    reject_args = parser.parse_args(
        ["launch", "reject", "launch-1", "-f", "Narrow the request"]
    )
    request_args = parser.parse_args(
        [
            "launch",
            "request",
            "-p",
            "Do work",
            "-r",
            "Need a reviewer",
            "-m",
            "2",
            "-o",
            "json",
        ]
    )

    assert approve_args.command == "launch"
    assert approve_args.launch_subcommand == "approve"
    assert approve_args.selector == "launch-1"
    assert reject_args.launch_subcommand == "reject"
    assert reject_args.selector == "launch-1"
    assert reject_args.feedback == "Narrow the request"
    assert request_args.launch_subcommand == "request"
    assert request_args.prompt == "Do work"
    assert request_args.reason == "Need a reviewer"
    assert request_args.max_slots == 2
    assert request_args.output == "json"


def test_launch_help_renders_sorted_subcommands() -> None:
    """``sase launch --help`` lists child commands alphabetically."""
    launch_parser = parser_for(("sase", "launch"))
    expected_commands = {"approve", "reject", "request"}

    help_commands = help_subcommand_rows(launch_parser.format_help(), expected_commands)

    assert help_commands == sorted(expected_commands)


def test_launch_public_long_options_have_short_aliases() -> None:
    """Every public long option under ``sase launch`` has a short alias."""
    for subcommand in ("reject", "request"):
        parser = parser_for(("sase", "launch", subcommand))
        for action in parser._actions:
            public_long_options = [
                option
                for option in action.option_strings
                if option.startswith("--") and option != "--help"
            ]
            if not public_long_options:
                continue
            short_options = [
                option
                for option in action.option_strings
                if option.startswith("-") and not option.startswith("--")
            ]
            assert short_options, f"sase launch {subcommand} " + "/".join(
                public_long_options
            )


def test_agent_launch_request_hands_off_and_prints_request_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = SimpleNamespace(
        request_id="launch-1",
        to_dict=lambda: {
            "request_id": "launch-1",
            "notification_id": "note-1",
            "response_dir": "/tmp/launch-1",
            "request_file": "/tmp/launch-1/request.json",
            "preview_file": "/tmp/launch-1/launch_preview.md",
            "response_file": "/tmp/launch-1/response.json",
        },
    )
    args = argparse.Namespace(
        launch_subcommand="request",
        output="json",
    )

    with (
        patch(
            "sase.main.launch_handler._create_request_from_cli", return_value=request
        ),
        patch(
            "sase.agent.launch_request.running_agent_context_requires_launch_approval",
            return_value=True,
        ),
        patch(
            "sase.agent.launch_request.maybe_handoff_launch_approval_from_agent",
            return_value=True,
        ) as handoff,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_launch_command(args)

    assert exc_info.value.code == 0
    handoff.assert_called_once_with(request)
    assert json.loads(capsys.readouterr().out)["request_id"] == "launch-1"
