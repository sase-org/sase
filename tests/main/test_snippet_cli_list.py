"""Tests for ``sase snippet list``."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.main.parser import create_parser
from sase.snippet import cli_list
from sase.xprompt.models import XPrompt

from .snippet_cli_helpers import install_writable_snippet_project


def _console(output: StringIO) -> Console:
    return Console(file=output, force_terminal=False, color_system=None, width=160)


def test_list_table_includes_trigger_origin_calls_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    output = StringIO()
    args = create_parser().parse_args(["snippet", "list", "-p", "demo"])

    cli_list.handle_snippet_list_command(args, console=_console(output))

    text = output.getvalue()
    assert "SNIPPET" in text
    assert "demo" in text
    assert "greet" in text
    assert "wrap" in text
    assert "2 snippets" in text
    assert "Hello $1!$0" in text
    assert "#[greet]$0" in text


def test_list_names_format_prints_one_trigger_per_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(["snippet", "list", "-f", "names", "-p", "demo"])

    cli_list.handle_snippet_list_command(args)

    assert capsys.readouterr().out.splitlines() == ["greet", "wrap"]


def test_list_pattern_filters_triggers_and_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(
        ["snippet", "list", "Greet", "-f", "names", "-p", "demo"]
    )

    cli_list.handle_snippet_list_command(args)

    assert capsys.readouterr().out.splitlines() == ["greet"]


def test_list_pattern_requires_definitions_flag_to_match_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)

    without_flag = create_parser().parse_args(
        ["snippet", "list", "#[greet]", "-f", "names", "-p", "demo"]
    )
    cli_list.handle_snippet_list_command(without_flag)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no snippets matched: #[greet]" in captured.err

    with_flag = create_parser().parse_args(
        ["snippet", "list", "#[greet]", "--definitions", "-f", "names", "-p", "demo"]
    )
    cli_list.handle_snippet_list_command(with_flag)
    assert capsys.readouterr().out.splitlines() == ["wrap"]


def test_list_json_format_is_deterministic_and_includes_relations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(
        ["snippet", "list", "wrap", "-f", "json", "-p", "demo"]
    )

    cli_list.handle_snippet_list_command(args)

    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert raw == json.dumps(payload, indent=2, sort_keys=True) + "\n"
    assert payload["project"] == "demo"
    assert payload["pattern"] == "wrap"
    assert [item["trigger"] for item in payload["snippets"]] == ["wrap"]
    snippet = payload["snippets"][0]
    assert snippet["raw_template"] == "#[greet]$0"
    assert "greet" in snippet["relations"]["outbound"]
    assert snippet["origin"]["kind"] == "project"
    assert "Wrap" in snippet["aliases"]
    assert "wrap" not in snippet["aliases"]


def test_list_json_empty_match_is_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(
        ["snippet", "list", "xyzzy", "-f", "json", "-p", "demo"]
    )

    cli_list.handle_snippet_list_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["snippets"] == []


def test_list_does_not_double_generated_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(["snippet", "list", "-f", "names", "-p", "demo"])

    cli_list.handle_snippet_list_command(args)

    names = capsys.readouterr().out.splitlines()
    assert "Greet" not in names
    assert "Wrap" not in names


def test_list_unknown_project_exits_with_context_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(["snippet", "list", "-p", "missing"])

    with pytest.raises(SystemExit) as exc:
        cli_list.handle_snippet_list_command(args)

    assert exc.value.code == 2
    assert "sase snippet list: no such project: missing" in capsys.readouterr().err


def test_list_includes_xprompt_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(
        tmp_path,
        monkeypatch,
        body="timezone: UTC\n",
        xprompts={
            "review": XPrompt(
                name="review",
                content="Review $0",
                snippet=True,
                source_path="xprompts/review.md",
            )
        },
    )
    args = create_parser().parse_args(["snippet", "list", "-f", "json", "-p", "demo"])

    cli_list.handle_snippet_list_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["snippets"][0]["origin"]["kind"] == "xprompt"
    assert payload["snippets"][0]["origin"]["writable"] is False
