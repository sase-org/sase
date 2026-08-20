"""Tests for ``sase snippet add``."""

from __future__ import annotations

import json
import shlex
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
import yaml

from sase.main.parser import create_parser
from sase.snippet import cli_add
from sase.xprompt.models import XPrompt
from sase.xprompt.snippet_config_yaml import snippet_config_digest

from .snippet_cli_helpers import install_writable_snippet_project


def _console(output: StringIO) -> Console:
    return Console(file=output, force_terminal=False, color_system=None, width=160)


def test_add_rich_format_states_created_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = install_writable_snippet_project(
        tmp_path, monkeypatch, body="timezone: UTC\n"
    )
    output = StringIO()
    args = create_parser().parse_args(
        [
            "snippet",
            "add",
            "todo",
            "TODO($1)$0",
            "-p",
            "demo",
            "-t",
            str(config_path),
        ]
    )

    cli_add.handle_snippet_add_command(args, console=_console(output))

    text = output.getvalue()
    assert "CREATED" in text
    assert "todo" in text
    assert str(config_path) in text
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert loaded["ace"]["snippets"]["todo"] == "TODO($1)$0"


def test_add_json_format_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = install_writable_snippet_project(
        tmp_path, monkeypatch, body="timezone: UTC\n"
    )
    args = create_parser().parse_args(
        [
            "snippet",
            "add",
            "todo",
            "TODO($1)$0",
            "-p",
            "demo",
            "-t",
            str(config_path),
            "-f",
            "json",
        ]
    )

    cli_add.handle_snippet_add_command(args)

    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert raw == json.dumps(payload, indent=2, sort_keys=True) + "\n"
    assert payload["action"] == "created"
    assert payload["created"] is True
    assert payload["dry_run"] is False
    assert payload["project"] == "demo"
    assert payload["trigger"] == "todo"
    assert payload["template"] == "TODO($1)$0"
    assert payload["write_path"] == str(config_path)
    assert payload["removed_paths"] == []


def test_add_dry_run_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = install_writable_snippet_project(
        tmp_path, monkeypatch, body="timezone: UTC\n"
    )
    original = config_path.read_text(encoding="utf-8")
    digest_before = snippet_config_digest(config_path.read_bytes())
    args = create_parser().parse_args(
        [
            "snippet",
            "add",
            "todo",
            "TODO($1)$0",
            "-p",
            "demo",
            "-t",
            str(config_path),
            "-n",
        ]
    )

    cli_add.handle_snippet_add_command(args, console=_console(StringIO()))

    assert config_path.read_text(encoding="utf-8") == original
    assert snippet_config_digest(config_path.read_bytes()) == digest_before


def test_add_refuses_overwrite_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = install_writable_snippet_project(tmp_path, monkeypatch)
    original = config_path.read_bytes()
    args = create_parser().parse_args(
        [
            "snippet",
            "add",
            "greet",
            "NEW$0",
            "-p",
            "demo",
            "-t",
            str(config_path),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        cli_add.handle_snippet_add_command(args)

    assert exc.value.code == 3
    err = capsys.readouterr().err
    assert "sase snippet add:" in err
    assert "already exists" in err
    assert config_path.read_bytes() == original


def test_add_force_replaces_and_reports_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(
        [
            "snippet",
            "add",
            "greet",
            "NEW$0",
            "-p",
            "demo",
            "-t",
            str(config_path),
            "-F",
            "-f",
            "json",
        ]
    )

    cli_add.handle_snippet_add_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "replaced"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert loaded["ace"]["snippets"]["greet"] == "NEW$0"


def test_add_force_shadows_xprompt_and_reports_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = install_writable_snippet_project(
        tmp_path,
        monkeypatch,
        body="timezone: UTC\n",
        xprompts={"todo": XPrompt(name="todo", content="from xprompt", snippet=True)},
    )
    args = create_parser().parse_args(
        [
            "snippet",
            "add",
            "todo",
            "from config$0",
            "-p",
            "demo",
            "-t",
            str(config_path),
            "-F",
            "-f",
            "json",
        ]
    )

    cli_add.handle_snippet_add_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "shadowed"
    assert "-F" in payload["restore_command"]


def test_add_invalid_trigger_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = install_writable_snippet_project(
        tmp_path, monkeypatch, body="timezone: UTC\n"
    )
    args = create_parser().parse_args(
        [
            "snippet",
            "add",
            "bad-name!",
            "body$0",
            "-p",
            "demo",
            "-t",
            str(config_path),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        cli_add.handle_snippet_add_command(args)

    assert exc.value.code == 3
    assert "sase snippet add:" in capsys.readouterr().err


def test_add_restore_command_round_trips_multiline_and_spaced_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "work space"
    workspace.mkdir()
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )
    from sase.xprompt import glossary_catalog as catalog_mod

    from .snippet_cli_helpers import project_record

    config_path = workspace / "sase" / "sase.yml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("timezone: UTC\n", encoding="utf-8")
    monkeypatch.setattr(
        catalog_mod,
        "list_project_records",
        lambda *_a, **_kw: [project_record(workspace)],
    )
    template = "line one\nline two $0"
    args = create_parser().parse_args(
        [
            "snippet",
            "add",
            "todo",
            template,
            "-p",
            "demo",
            "-t",
            str(config_path),
            "-f",
            "json",
        ]
    )

    cli_add.handle_snippet_add_command(args)

    payload = json.loads(capsys.readouterr().out)
    tokens = shlex.split(payload["restore_command"])
    restored = create_parser().parse_args(tokens[1:])
    assert tokens[0] == "sase"
    assert restored.command == "snippet"
    assert restored.snippet_subcommand == "add"
    assert restored.trigger == "todo"
    assert restored.template == template
    assert restored.target == str(config_path)
    assert restored.project == "demo"
