"""Tests for ``sase glossary add``."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
import yaml

from sase.core.glossary_facade import GlossaryDiagnostic
from sase.glossary import cli_add, cli_write
from sase.glossary.cli_common import GlossaryCliError
from sase.glossary.mutation import GlossaryValidationError
from sase.main.parser import create_parser

from .glossary_cli_helpers import (
    install_writable_glossary_project,
    mutation_outcome,
)


def _console(output: StringIO) -> Console:
    return Console(file=output, force_terminal=False, color_system=None, width=160)


def _patch_add(
    monkeypatch: pytest.MonkeyPatch,
    outcome=None,
    *,
    error: BaseException | None = None,
) -> None:
    def fake_add(*_a: object, **_kw: object):
        if error is not None:
            raise error
        return outcome or mutation_outcome()

    monkeypatch.setattr(cli_add, "add_glossary_term", fake_add)
    monkeypatch.setattr(cli_write, "_maybe_regenerate", lambda *_a, **_kw: (True, None))


def test_add_rich_format_prints_project_term_aliases_and_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = mutation_outcome()
    _patch_add(monkeypatch, outcome)
    output = StringIO()
    args = create_parser().parse_args(
        ["glossary", "add", "Widget Box", "A container for widgets.", "-a", "box"]
    )

    cli_add.handle_glossary_add_command(args, console=_console(output))

    text = output.getvalue()
    assert "ADDED" in text
    assert "demo" in text
    assert "Widget Box" in text
    assert "box" in text
    assert outcome.config_path in text
    assert "Regenerated agent instruction files for demo." in text


def test_add_json_format_includes_stable_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outcome = mutation_outcome(created_section=True)
    _patch_add(monkeypatch, outcome)
    args = create_parser().parse_args(
        ["glossary", "add", "Widget Box", "A container for widgets.", "-f", "json"]
    )

    cli_add.handle_glossary_add_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "aliases": ["box"],
        "config_path": outcome.config_path,
        "created_section": True,
        "definition": "A container for widgets.",
        "initialized": True,
        "operation": "add",
        "project": "demo",
        "term": "Widget Box",
    }


def test_add_no_init_skips_regeneration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "sase" / "sase.yml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("memory:\n  glossary: {}\n", encoding="utf-8")
    outcome = mutation_outcome(
        config_path=str(config_path), workspace_dir=str(tmp_path)
    )
    monkeypatch.setattr(cli_add, "add_glossary_term", lambda *_a, **_kw: outcome)
    seen: list[Path] = []
    monkeypatch.setattr(
        cli_write,
        "_run_init_memory",
        lambda workspace: seen.append(workspace) or (True, None),
    )
    args = create_parser().parse_args(
        ["glossary", "add", "Widget Box", "A container.", "-I"]
    )

    cli_add.handle_glossary_add_command(args, console=_console(StringIO()))

    assert seen == []


def test_add_default_regenerates_instruction_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "sase" / "sase.yml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("memory:\n  glossary: {}\n", encoding="utf-8")
    outcome = mutation_outcome(
        config_path=str(config_path), workspace_dir=str(tmp_path)
    )
    monkeypatch.setattr(cli_add, "add_glossary_term", lambda *_a, **_kw: outcome)
    seen: list[Path] = []
    monkeypatch.setattr(
        cli_write,
        "_run_init_memory",
        lambda workspace: seen.append(workspace) or (True, None),
    )
    args = create_parser().parse_args(["glossary", "add", "Widget Box", "A container."])

    cli_add.handle_glossary_add_command(args, console=_console(StringIO()))

    assert seen == [tmp_path]


def test_add_validation_failure_exits_nonzero_and_prints_diagnostic(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    diagnostic = GlossaryDiagnostic(
        severity="error",
        code="duplicate_term",
        message="term already exists",
        path="glossary.Alpha",
    )
    _patch_add(
        monkeypatch,
        error=GlossaryValidationError((diagnostic,)),
    )
    monkeypatch.setattr(
        cli_write,
        "_config_path_for_diagnostics",
        lambda _ref: "/tmp/demo/sase/sase.yml",
    )
    args = create_parser().parse_args(
        ["glossary", "add", "Alpha", "A colliding definition."]
    )

    with pytest.raises(SystemExit) as exc:
        cli_add.handle_glossary_add_command(args)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "sase glossary add:" in err
    assert "/tmp/demo/sase/sase.yml" in err
    assert "memory.glossary.Alpha" in err
    assert "duplicate_term: term already exists" in err


def test_add_unknown_project_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_add(monkeypatch, error=GlossaryCliError("no such project"))
    args = create_parser().parse_args(
        ["glossary", "add", "Term", "A definition.", "-p", "missing"]
    )

    with pytest.raises(SystemExit) as exc:
        cli_add.handle_glossary_add_command(args)

    assert exc.value.code == 1
    assert "no such project" in capsys.readouterr().err


def test_add_validation_leaves_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = install_writable_glossary_project(tmp_path, monkeypatch)
    original = config_path.read_bytes()
    monkeypatch.setattr(
        cli_write, "_maybe_regenerate", lambda *_a, **_kw: (False, None)
    )
    args = create_parser().parse_args(
        ["glossary", "add", "Alpha", "A colliding definition.", "-p", "demo", "-I"]
    )

    with pytest.raises(SystemExit) as exc:
        cli_add.handle_glossary_add_command(args)

    assert exc.value.code == 1
    assert config_path.read_bytes() == original
    assert "sase glossary add:" in capsys.readouterr().err


def test_add_init_failure_is_warning_not_rollback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "sase" / "sase.yml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("memory:\n  glossary: {}\n", encoding="utf-8")
    outcome = mutation_outcome(
        config_path=str(config_path), workspace_dir=str(tmp_path)
    )
    monkeypatch.setattr(cli_add, "add_glossary_term", lambda *_a, **_kw: outcome)
    monkeypatch.setattr(
        cli_write,
        "_run_init_memory",
        lambda _workspace: (
            False,
            "failed to regenerate agent instruction files; run `sase memory init`",
        ),
    )
    args = create_parser().parse_args(
        ["glossary", "add", "Widget Box", "A container.", "-f", "json"]
    )

    cli_add.handle_glossary_add_command(args)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["initialized"] is False
    assert payload["init_warning"]
    assert "sase memory init" in captured.err
    assert "warning:" in captured.err


def test_add_happy_path_writes_sorted_term(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = install_writable_glossary_project(tmp_path, monkeypatch)
    monkeypatch.setattr(cli_write, "_maybe_regenerate", lambda *_a, **_kw: (True, None))
    args = create_parser().parse_args(
        ["glossary", "add", "Beta", "The middle term.", "-p", "demo", "-a", "b"]
    )

    cli_add.handle_glossary_add_command(args, console=_console(StringIO()))

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert list(loaded["memory"]["glossary"]) == ["Alpha", "Beta", "Gamma"]
    assert loaded["memory"]["glossary"]["Beta"]["aliases"] == ["b"]
