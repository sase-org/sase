"""Tests for the ``sase completion`` handler."""

from __future__ import annotations

import json
from argparse import Namespace
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.completion.snapshot import current_structural_view
from sase.main.completion_handler import (
    _ShellRow,
    _handle_completion_list,
    handle_completion_command,
)
from sase.main.parser import create_parser


def _console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, highlight=False, color_system=None, width=80), buf


def test_list_renders_zsh_generator_and_pending_shells() -> None:
    console, buf = _console()
    args = create_parser().parse_args(["completion", "list"])

    assert _handle_completion_list(args, console=console) == 0
    text = buf.getvalue()
    assert "SHELL" in text
    assert "GENERATOR" in text
    assert "STATUS" in text
    assert "zsh" in text
    assert "yes" in text
    assert "not installed" in text
    assert "bash" in text
    assert "fish" in text


def test_list_json_payload(capsys: pytest.CaptureFixture[str]) -> None:
    args = create_parser().parse_args(["completion", "list", "--json"])

    assert handle_completion_command(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    shells = {row["shell"]: row for row in payload["shells"]}
    assert shells["zsh"] == {
        "generator": True,
        "shell": "zsh",
        "status": "not installed",
    }
    assert shells["bash"]["generator"] is False
    assert shells["fish"]["generator"] is False


def test_list_accepts_injected_rows_for_later_columns() -> None:
    console, buf = _console()
    rows = (
        _ShellRow("zsh", True, "available"),
        _ShellRow("bash", True, "pending"),
    )
    args = create_parser().parse_args(["completion", "list"])

    assert _handle_completion_list(args, console=console, rows=rows) == 0
    text = buf.getvalue()
    assert "available" in text
    assert "bash" in text


def test_spec_prints_structural_snapshot(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["completion", "spec"])

    assert handle_completion_command(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == current_structural_view()
    assert payload["prog"] == "sase"
    names = {child["name"] for child in payload["root"]["subcommands"]}
    assert "completion" in names


def test_spec_and_zsh_write_output_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_path = tmp_path / "spec.json"
    zsh_path = tmp_path / "_sase"
    spec_args = create_parser().parse_args(["completion", "spec", "-o", str(spec_path)])
    zsh_args = create_parser().parse_args(["completion", "zsh", "-o", str(zsh_path)])

    assert handle_completion_command(spec_args) == 0
    assert handle_completion_command(zsh_args) == 0
    assert capsys.readouterr().out == ""
    assert (
        json.loads(spec_path.read_text(encoding="utf-8")) == current_structural_view()
    )
    zsh_text = zsh_path.read_text(encoding="utf-8")
    assert zsh_text.startswith("#compdef sase\n")
    assert "_arguments -C -s -S" in zsh_text


def test_zsh_prints_compdef_script(capsys: pytest.CaptureFixture[str]) -> None:
    args = create_parser().parse_args(["completion", "zsh"])

    assert handle_completion_command(args) == 0
    script = capsys.readouterr().out
    assert script.startswith("#compdef sase\n")
    assert "_sase_run()" in script


def test_write_output_reports_unwritable_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "no-such-dir" / "_sase"
    args = create_parser().parse_args(["completion", "zsh", "-o", str(missing)])

    assert handle_completion_command(args) == 1
    assert "cannot write" in capsys.readouterr().err


def test_dispatch_unknown_subcommand_exits_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert handle_completion_command(Namespace(completion_subcommand="nope")) == 2
    assert "Usage: sase completion" in capsys.readouterr().err
