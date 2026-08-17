"""Tests for ``sase glossary del``."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
import yaml

from sase.glossary import cli_del, cli_write
from sase.glossary.cli_common import GlossaryCliError
from sase.glossary.resolution import GlossaryLookupError
from sase.main.parser import create_parser

from .glossary_cli_helpers import (
    install_writable_glossary_project,
    mutation_outcome,
)


def _console(output: StringIO) -> Console:
    return Console(file=output, force_terminal=False, color_system=None, width=160)


def _patch_delete(
    monkeypatch: pytest.MonkeyPatch,
    outcome=None,
    *,
    error: BaseException | None = None,
    captured: list[dict[str, object]] | None = None,
) -> None:
    def fake_delete(*_a: object, **kwargs: object):
        if captured is not None:
            captured.append(dict(kwargs))
        if error is not None:
            raise error
        return outcome or mutation_outcome(
            term="Gamma",
            aliases=("g",),
            definition="Third term mentions Alpha.",
            restore_command=(
                "sase glossary add Gamma 'Third term mentions Alpha.' -a g -p demo"
            ),
            referenced_by=("Alpha",),
        )

    monkeypatch.setattr(cli_del, "delete_glossary_term", fake_delete)
    monkeypatch.setattr(
        cli_write, "_maybe_regenerate", lambda *_a, **_kw: (False, None)
    )


def test_del_rich_format_prints_restore_and_inbound_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = mutation_outcome(
        term="Gamma",
        aliases=("g",),
        referenced_by=("Alpha",),
        restore_command=(
            "sase glossary add Gamma 'Third term mentions Alpha.' -a g -p demo"
        ),
    )
    _patch_delete(monkeypatch, outcome)
    output = StringIO()
    args = create_parser().parse_args(["glossary", "del", "g"])

    cli_del.handle_glossary_del_command(args, console=_console(output))

    text = output.getvalue()
    assert "DELETED" in text
    assert "demo" in text
    assert "Gamma" in text
    assert "g" in text
    assert "1 · Alpha" in text
    assert outcome.restore_command in text
    assert outcome.config_path in text


def test_del_json_format_includes_restore_and_referenced_by(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outcome = mutation_outcome(
        term="Gamma",
        aliases=("g",),
        referenced_by=("Alpha",),
        restore_command=(
            "sase glossary add Gamma 'Third term mentions Alpha.' -a g -p demo"
        ),
    )
    _patch_delete(monkeypatch, outcome)
    args = create_parser().parse_args(["glossary", "del", "Gamma", "-f", "json"])

    cli_del.handle_glossary_del_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "del"
    assert payload["term"] == "Gamma"
    assert payload["aliases"] == ["g"]
    assert payload["referenced_by"] == ["Alpha"]
    assert payload["restore_command"] == outcome.restore_command
    assert payload["dry_run"] is False
    assert payload["initialized"] is False
    assert payload["project"] == "demo"


def test_del_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = install_writable_glossary_project(tmp_path, monkeypatch)
    original = config_path.read_bytes()
    seen: list[Path] = []
    monkeypatch.setattr(
        cli_write,
        "_run_init_memory",
        lambda workspace: seen.append(workspace) or (True, None),
    )
    output = StringIO()
    args = create_parser().parse_args(["glossary", "del", "g", "-n", "-p", "demo"])

    cli_del.handle_glossary_del_command(args, console=_console(output))

    assert config_path.read_bytes() == original
    assert seen == []
    text = output.getvalue()
    assert "DELETED" in text
    assert "Gamma" in text
    assert "sase glossary add" in text


def test_del_dry_run_json_sets_flag_and_skips_init(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: list[dict[str, object]] = []
    _patch_delete(monkeypatch, captured=captured)
    args = create_parser().parse_args(["glossary", "del", "Gamma", "-n", "-f", "json"])

    cli_del.handle_glossary_del_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert captured == [{"dry_run": True}]


def test_del_unknown_term_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_delete(monkeypatch, error=GlossaryLookupError("xyzzy"))
    args = create_parser().parse_args(["glossary", "del", "xyzzy"])

    with pytest.raises(SystemExit) as exc:
        cli_del.handle_glossary_del_command(args)

    assert exc.value.code == 1
    assert "unknown glossary term: xyzzy" in capsys.readouterr().err


def test_del_unknown_project_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_delete(monkeypatch, error=GlossaryCliError("no such project"))
    args = create_parser().parse_args(["glossary", "del", "Gamma", "-p", "missing"])

    with pytest.raises(SystemExit) as exc:
        cli_del.handle_glossary_del_command(args)

    assert exc.value.code == 1
    assert "no such project" in capsys.readouterr().err


def test_del_happy_path_removes_term(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = install_writable_glossary_project(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli_write, "_maybe_regenerate", lambda *_a, **_kw: (False, None)
    )
    args = create_parser().parse_args(["glossary", "del", "g", "-p", "demo", "-I"])

    cli_del.handle_glossary_del_command(args, console=_console(StringIO()))

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert "Gamma" not in loaded["memory"]["glossary"]
    assert "Alpha" in loaded["memory"]["glossary"]
