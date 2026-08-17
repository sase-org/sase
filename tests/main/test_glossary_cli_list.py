"""Tests for ``sase glossary list``."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from rich.console import Console

from sase.core.glossary_facade import GlossaryEntry
from sase.glossary import cli_list
from sase.glossary.cli_common import GlossaryCliError, ResolvedGlossaryProject
from sase.main.parser import create_parser

from .glossary_cli_helpers import (
    FakeCompiledGlossaryCatalog,
    glossary_entry,
    glossary_span,
    resolved_glossary_project,
)


def _entries() -> tuple[GlossaryEntry, ...]:
    return (
        glossary_entry(0, "Agent Hood", "A group of agents.", aliases=("hood",)),
        glossary_entry(1, "Sase Agent", "See Agent Hood.", aliases=("agent",)),
        glossary_entry(2, "Stitch", "A commit, proposal, or PR."),
    )


def _patch_resolved(
    monkeypatch: pytest.MonkeyPatch, resolved: ResolvedGlossaryProject
) -> None:
    monkeypatch.setattr(
        cli_list, "resolve_glossary_cli_project", lambda *_a, **_kw: resolved
    )


def test_list_table_format_includes_project_header_and_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = _entries()
    compiled = FakeCompiledGlossaryCatalog(
        {"See Agent Hood.": (glossary_span(0, "Agent Hood"),)}
    )
    resolved = resolved_glossary_project(entries=entries, compiled=compiled)
    _patch_resolved(monkeypatch, resolved)

    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=160)
    args = create_parser().parse_args(["glossary", "list"])

    cli_list.handle_glossary_list_command(args, console=console)

    text = output.getvalue()
    assert "GLOSSARY" in text
    assert "sase" in text
    assert "Agent Hood" in text
    assert "Sase Agent" in text
    assert "Stitch" in text
    assert "3 terms" in text


def test_list_names_format_prints_one_term_per_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    resolved = resolved_glossary_project(entries=_entries())
    _patch_resolved(monkeypatch, resolved)
    args = create_parser().parse_args(["glossary", "list", "-f", "names"])

    cli_list.handle_glossary_list_command(args)

    out = capsys.readouterr().out
    assert out.splitlines() == ["Agent Hood", "Sase Agent", "Stitch"]


def test_list_pattern_filters_terms_and_aliases(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    resolved = resolved_glossary_project(entries=_entries())
    _patch_resolved(monkeypatch, resolved)
    args = create_parser().parse_args(["glossary", "list", "hood", "-f", "names"])

    cli_list.handle_glossary_list_command(args)

    assert capsys.readouterr().out.splitlines() == ["Agent Hood"]


def test_list_pattern_requires_definitions_flag_to_match_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    resolved = resolved_glossary_project(entries=_entries())
    _patch_resolved(monkeypatch, resolved)

    without_flag = create_parser().parse_args(
        ["glossary", "list", "commit", "-f", "names"]
    )
    cli_list.handle_glossary_list_command(without_flag)
    assert capsys.readouterr().out == "no terms matched: commit\n"

    with_flag = create_parser().parse_args(
        ["glossary", "list", "commit", "--definitions", "-f", "names"]
    )
    cli_list.handle_glossary_list_command(with_flag)
    assert capsys.readouterr().out.splitlines() == ["Stitch"]


def test_list_json_format_includes_aliases_refs_and_source(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    entries = _entries()
    compiled = FakeCompiledGlossaryCatalog(
        {"See Agent Hood.": (glossary_span(0, "Agent Hood"),)}
    )
    resolved = resolved_glossary_project(entries=entries, compiled=compiled)
    _patch_resolved(monkeypatch, resolved)
    args = create_parser().parse_args(["glossary", "list", "sase agent", "-f", "json"])

    cli_list.handle_glossary_list_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["project"] == "sase"
    assert payload["pattern"] == "sase agent"
    assert payload["terms"] == [
        {
            "term": "Sase Agent",
            "aliases": ["agent"],
            "definition": "See Agent Hood.",
            "reference_terms": ["Agent Hood"],
            "source": {"config_path": "sase/sase.yml"},
        }
    ]


def test_list_json_empty_match_is_empty_list_not_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    resolved = resolved_glossary_project(entries=_entries())
    _patch_resolved(monkeypatch, resolved)
    args = create_parser().parse_args(["glossary", "list", "xyzzy", "-f", "json"])

    cli_list.handle_glossary_list_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["terms"] == []


def test_list_exits_nonzero_on_project_resolution_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_resolve(*_a: object, **_kw: object) -> ResolvedGlossaryProject:
        raise GlossaryCliError("no such project: missing")

    monkeypatch.setattr(cli_list, "resolve_glossary_cli_project", fake_resolve)
    args = create_parser().parse_args(["glossary", "list", "-p", "missing"])

    with pytest.raises(SystemExit) as exc:
        cli_list.handle_glossary_list_command(args)

    assert exc.value.code == 1
    assert "no such project: missing" in capsys.readouterr().err
