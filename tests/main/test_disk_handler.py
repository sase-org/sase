"""Parser tests for ``sase disk``."""

from __future__ import annotations

import argparse

from sase.core.disk_footprint_models import DISK_SIZE_LOWER_BOUND
from sase.core.disk_footprint_models import DISK_SIZE_UNMEASURED
from sase.core.disk_footprint_models import DiskFootprintReport
from sase.core.disk_footprint_models import DiskFootprintRow
from sase.core.disk_footprint_models import DiskReapResult, DiskReapStep
from sase.main.disk_handler import _exit_code
from sase.main.disk_handler import _handle_reap
from sase.main.disk_handler import _print_disk_report
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


def test_print_disk_report_renders_unmeasured_and_lower_bound(
    capsys,
) -> None:
    report = DiskFootprintReport(
        rows=(
            DiskFootprintRow(
                section="workspaces",
                name="ws",
                path="/tmp/ws",
                size_bytes=0,
                owner="workspace_cleanup_and_compact",
                horizon="cleanup TTL 14 day(s)",
                size_state=DISK_SIZE_UNMEASURED,
                coverage="partial",
            ),
            DiskFootprintRow(
                section="sase_home",
                name="tools",
                path="/tmp/tools",
                size_bytes=2048,
                owner="tool_run_retention",
                horizon="summary 180d",
                size_state=DISK_SIZE_LOWER_BOUND,
                coverage="partial",
            ),
        ),
        generated_at="now",
        physical_total_bytes=2048,
        logical_total_bytes=2048,
        coverage_status="partial",
        unmeasured_owners=("workspace_cleanup_and_compact /tmp/ws",),
        totals_are_lower_bound=True,
    )

    _print_disk_report(report)
    output = capsys.readouterr().out

    assert "unmeasured" in output
    assert "≥2.0 KiB" in output
    assert "0 B" not in output
    assert "1 owner unmeasured" in output
    assert "≥2.0 KiB attributed" in output


def test_handle_reap_does_not_collect_inventory(monkeypatch, capsys) -> None:
    called: list[str] = []

    def boom() -> object:
        called.append("inventory")
        raise RuntimeError("inventory must not run")

    monkeypatch.setattr("sase.main.disk_handler.collect_disk_footprint", boom)
    monkeypatch.setattr(
        "sase.main.disk_handler.run_disk_reap",
        lambda **_kwargs: DiskReapResult(apply=False, project=None, steps=()),
    )
    args = argparse.Namespace(apply=False, json=True, project=None)

    assert _handle_reap(args) == 0
    assert called == []
    assert '"apply": false' in capsys.readouterr().out


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
