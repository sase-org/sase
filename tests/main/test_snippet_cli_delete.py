"""Tests for ``sase snippet delete``."""

from __future__ import annotations

import json
import shlex
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
import yaml

from sase.main.parser import create_parser
from sase.snippet import cli_delete
from sase.xprompt.models import XPrompt

from .snippet_cli_helpers import install_writable_snippet_project


def _console(output: StringIO) -> Console:
    return Console(file=output, force_terminal=False, color_system=None, width=160)


def test_delete_rich_format_prints_restore_and_removed_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = install_writable_snippet_project(tmp_path, monkeypatch)
    output = StringIO()
    args = create_parser().parse_args(["snippet", "delete", "greet", "-p", "demo"])

    cli_delete.handle_snippet_delete_command(args, console=_console(output))

    text = output.getvalue()
    assert "DELETED" in text
    assert "greet" in text
    assert "sase snippet add" in text
    assert str(config_path) in text
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    snippets = (loaded.get("ace") or {}).get("snippets") or {}
    assert "greet" not in snippets


def test_delete_json_includes_restore_and_revealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = install_writable_snippet_project(
        tmp_path,
        monkeypatch,
        xprompts={
            "greet": XPrompt(
                name="greet",
                content="from xprompt",
                snippet=True,
                source_path="xprompts/greet.md",
            )
        },
    )
    args = create_parser().parse_args(
        ["snippet", "delete", "greet", "-p", "demo", "-f", "json"]
    )

    cli_delete.handle_snippet_delete_command(args)

    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert raw == json.dumps(payload, indent=2, sort_keys=True) + "\n"
    assert payload["action"] == "deleted"
    assert payload["trigger"] == "greet"
    assert payload["removed_paths"] == [str(config_path)]
    assert payload["revealed"] is not None
    assert payload["revealed"]["origin"]["kind"] == "xprompt"
    assert "-F" in payload["restore_command"]
    tokens = shlex.split(payload["restore_command"])
    restored = create_parser().parse_args(tokens[1:])
    assert restored.force is True
    assert restored.trigger == "greet"


def test_delete_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = install_writable_snippet_project(tmp_path, monkeypatch)
    original = config_path.read_bytes()
    args = create_parser().parse_args(
        ["snippet", "delete", "greet", "-p", "demo", "-n"]
    )

    cli_delete.handle_snippet_delete_command(args, console=_console(StringIO()))

    assert config_path.read_bytes() == original


def test_delete_maps_alias_to_explicit_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(
        ["snippet", "delete", "Greet", "-p", "demo", "-f", "json"]
    )

    cli_delete.handle_snippet_delete_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["trigger"] == "greet"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    snippets = (loaded.get("ace") or {}).get("snippets") or {}
    assert "greet" not in snippets


def test_delete_refuses_xprompt_only_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(
        tmp_path,
        monkeypatch,
        body="timezone: UTC\n",
        xprompts={
            "todo": XPrompt(
                name="todo",
                content="from xprompt",
                snippet=True,
                source_path="xprompts/todo.md",
            )
        },
    )
    args = create_parser().parse_args(["snippet", "delete", "todo", "-p", "demo"])

    with pytest.raises(SystemExit) as exc:
        cli_delete.handle_snippet_delete_command(args)

    assert exc.value.code == 3
    err = capsys.readouterr().err
    assert "sase snippet delete:" in err
    assert "cannot delete" in err
    assert "xprompts/todo.md" in err or "xprompt" in err


def test_delete_unknown_trigger_exits_with_lookup_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(["snippet", "delete", "xyzzy", "-p", "demo"])

    with pytest.raises(SystemExit) as exc:
        cli_delete.handle_snippet_delete_command(args)

    assert exc.value.code == 1
    assert "unknown snippet trigger: xyzzy" in capsys.readouterr().err


def test_delete_reports_backlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(
        ["snippet", "delete", "greet", "-p", "demo", "-f", "json"]
    )

    cli_delete.handle_snippet_delete_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert "wrap" in payload["affected_backlinks"]
