"""Parser and handler coverage for service-host and scheduler command surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.feature_flags import override_flags
from sase.main.parser import _DEFAULT_LIST_GROUP_DEST, create_parser
from sase.main.service_handler import handle_service_command
from sase.procs.service_meta import (
    SERVICE_PROC_MODE_ONESHOT,
    SERVICE_PROC_SOURCE_TRANSIENT,
)
from tests.main.parser_cli_helpers import parse_sase_args
from tests.main.parser_help_helpers import flat_help, help_subcommand_rows, parser_for


def test_service_help_lists_sorted_subcommands() -> None:
    parser = parser_for(("sase", "service"))
    help_text = parser.format_help()
    expected = {
        "init",
        "logs",
        "proc",
        "restart",
        "run",
        "start",
        "status",
        "stop",
        "uninstall",
    }

    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "Bare `sase service` is harmless" in flat_help(help_text)


def test_service_proc_bare_defaults_to_list() -> None:
    parser = create_parser()

    bare = parser.parse_args(["service", "proc"])

    assert bare.command == "service"
    assert bare.service_subcommand == "proc"
    assert bare.service_proc_subcommand == "list"
    assert getattr(bare, _DEFAULT_LIST_GROUP_DEST) == "sase service proc"


def test_service_proc_run_parser_carries_transient_options() -> None:
    args = create_parser().parse_args(
        [
            "service",
            "proc",
            "run",
            "-c",
            "/tmp",
            "-l",
            "One shot",
            "-p",
            "sase",
            "-w",
            "17",
            "--",
            "echo",
            "ok",
        ]
    )

    assert args.cwd == "/tmp"
    assert args.label == "One shot"
    assert args.project == "sase"
    assert args.workspace == 17
    assert args.proc_command == ["--", "echo", "ok"]


def test_scheduler_help_lists_sorted_subcommands() -> None:
    parser = parser_for(("sase", "scheduler"))
    help_text = parser.format_help()
    expected = {"restart", "run", "start", "status", "stop"}

    assert help_subcommand_rows(help_text, expected) == sorted(expected)
    assert "legacy AXE lifecycle behavior" in flat_help(help_text)


def test_service_flag_off_fails_with_opt_in_diagnostic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = parse_sase_args(["service", "status"])

    with override_flags(service_host=False):
        with pytest.raises(SystemExit) as exit_info:
            handle_service_command(args)

    assert exit_info.value.code == 2
    assert "service_host beta flag is disabled" in capsys.readouterr().err


def test_service_proc_run_submits_transient_oneshot_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}

    class _Proc:
        proc_id = "svc123456789"

    def fake_submit(request: object) -> _Proc:
        captured["request"] = request
        return _Proc()

    monkeypatch.setattr("sase.main.service_handler.submit_proc_request", fake_submit)
    args = parse_sase_args(
        [
            "service",
            "proc",
            "run",
            "-c",
            str(tmp_path),
            "-l",
            "Transient",
            "-p",
            "sase",
            "-w",
            "17",
            "--",
            "true",
        ]
    )

    with override_flags(service_host=True):
        with pytest.raises(SystemExit) as exit_info:
            handle_service_command(args)

    assert exit_info.value.code == 0
    request = captured["request"]
    assert request.cwd == tmp_path
    assert request.label == "Transient"
    assert request.project == "sase"
    assert request.workspace_num == 17
    assert request.service is not None
    assert request.service.name is None
    assert request.service.mode == SERVICE_PROC_MODE_ONESHOT
    assert request.service.source == SERVICE_PROC_SOURCE_TRANSIENT
    assert capsys.readouterr().out == "svc123456789\n"
