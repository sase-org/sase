"""Parser tests for ``sase disk``."""

from __future__ import annotations

import argparse

from sase.core.disk_footprint_models import DiskReapResult, DiskReapStep
from sase.main.disk_handler import _exit_code
from sase.main.parser import create_parser, default_list_delegation_notice


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    return next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )


def _long_options(parser: argparse.ArgumentParser) -> list[str]:
    result: list[str] = []
    for action in parser._actions:
        for option in action.option_strings:
            if option.startswith("--") and option != "--help":
                result.append(option)
    return sorted(result)


def test_parser_defaults_bare_disk_to_list_with_notice() -> None:
    args = create_parser().parse_args(["disk"])

    assert args.command == "disk"
    assert args.disk_subcommand == "list"
    assert args.json is False
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase disk'; delegating to 'sase disk list'."
    )


def test_parser_registers_disk_subcommands_and_short_options() -> None:
    parser = create_parser()
    disk = _subparser_action(parser).choices["disk"]
    subcommands = _subparser_action(disk)

    assert list(subcommands.choices) == ["list", "reap"]
    assert _long_options(subcommands.choices["list"]) == ["--json"]
    assert _long_options(subcommands.choices["reap"]) == [
        "--apply",
        "--json",
        "--project",
    ]
    args = parser.parse_args(["disk", "reap", "-a", "-j", "-p", "sase"])
    assert args.apply is True
    assert args.json is True
    assert args.project == "sase"


def test_reap_exit_code_fails_for_nonzero_owner_exit() -> None:
    result = DiskReapResult(
        apply=True,
        project=None,
        steps=(
            DiskReapStep(
                owner="proc_runtime_sweep",
                mode="apply",
                summary="errors=1",
                exit_code=1,
            ),
        ),
    )

    assert _exit_code(result) == 1
