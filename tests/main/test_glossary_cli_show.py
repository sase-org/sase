"""Tests for ``sase glossary show``."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from rich.console import Console

from sase.glossary import cli_show
from sase.glossary.cli_common import GlossaryCliError, ResolvedGlossaryProject
from sase.main.parser import create_parser

from .glossary_cli_helpers import (
    FakeCompiledGlossaryCatalog,
    glossary_entry,
    glossary_span,
    resolved_glossary_project,
)


def _diamond_resolved() -> ResolvedGlossaryProject:
    alpha = glossary_entry(0, "Alpha", "Mentions Beta then Gamma.")
    beta = glossary_entry(1, "Beta", "Mentions Delta.", aliases=("B",))
    gamma = glossary_entry(2, "Gamma", "Mentions Delta.")
    delta = glossary_entry(3, "Delta", "A leaf.")
    compiled = FakeCompiledGlossaryCatalog(
        {
            alpha.definition: (
                glossary_span(1, "Beta", start=9),
                glossary_span(2, "Gamma", start=19),
            ),
            beta.definition: (glossary_span(3, "Delta", start=9),),
            gamma.definition: (glossary_span(3, "Delta", start=9),),
        }
    )
    return resolved_glossary_project(
        entries=(alpha, beta, gamma, delta), compiled=compiled
    )


def _patch_resolved(
    monkeypatch: pytest.MonkeyPatch, resolved: ResolvedGlossaryProject
) -> None:
    monkeypatch.setattr(
        cli_show, "resolve_glossary_cli_project", lambda *_a, **_kw: resolved
    )


def test_show_rich_format_marks_requested_and_related_with_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=160)
    args = create_parser().parse_args(["glossary", "show", "Alpha"])

    cli_show.handle_glossary_show_command(args, console=console)

    text = output.getvalue()
    assert "REQUESTED" in text
    assert "RELATED · depth 1" in text
    assert "RELATED · depth 2" in text
    assert 'mentioned as "Beta" in Alpha' in text
    assert 'mentioned as "Delta" in Beta' in text
    assert "also mentioned by Gamma" in text
    assert "aka B" in text
    assert "4 terms · 1 requested · 3 related" in text
    assert "Use -d 0 to print only the requested terms." in text


def test_show_depth_zero_prints_only_requested_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=160)
    args = create_parser().parse_args(["glossary", "show", "Alpha", "-d", "0"])

    cli_show.handle_glossary_show_command(args, console=console)

    text = output.getvalue()
    assert "Alpha" in text
    assert "○ Beta" not in text
    assert "RELATED" not in text
    assert "1 term · 1 requested · 0 related" in text
    assert "Truncated at depth 0" in text


def test_show_markdown_format_uses_heading_per_term(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    args = create_parser().parse_args(
        ["glossary", "show", "Alpha", "-d", "1", "-f", "markdown"]
    )

    cli_show.handle_glossary_show_command(args)

    text = capsys.readouterr().out
    assert "# Alpha" in text
    assert "*Requested*" in text
    assert "## Beta" in text
    assert 'mentioned as "Beta" in Alpha' in text
    assert "## Gamma" in text


def test_show_json_format_includes_provenance_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    args = create_parser().parse_args(["glossary", "show", "Alpha", "-f", "json"])

    cli_show.handle_glossary_show_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["project"] == "sase"
    assert payload["depth_limit"] is None
    assert payload["truncated"] is False
    nodes_by_term = {node["term"]: node for node in payload["nodes"]}
    assert nodes_by_term["Alpha"]["origin"] == "requested"
    assert nodes_by_term["Alpha"]["referrer"] is None
    assert nodes_by_term["Delta"]["origin"] == "related"
    assert nodes_by_term["Delta"]["depth"] == 2
    assert nodes_by_term["Delta"]["referrer"] == {
        "term": "Beta",
        "matched_text": "Delta",
    }
    assert nodes_by_term["Delta"]["also_referenced_by"] == ["Gamma"]


def test_show_unknown_term_exits_nonzero_with_candidates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    args = create_parser().parse_args(["glossary", "show", "Zzz"])

    with pytest.raises(SystemExit) as exc:
        cli_show.handle_glossary_show_command(args)

    assert exc.value.code == 1
    assert "unknown glossary term: Zzz" in capsys.readouterr().err


def test_show_ambiguous_term_exits_nonzero_with_candidates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    entries = (
        glossary_entry(0, "Widget Box", "A box."),
        glossary_entry(1, "Widget Factory", "A factory."),
    )
    resolved = resolved_glossary_project(entries=entries)
    _patch_resolved(monkeypatch, resolved)
    args = create_parser().parse_args(["glossary", "show", "widget"])

    with pytest.raises(SystemExit) as exc:
        cli_show.handle_glossary_show_command(args)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "did you mean" in err
    assert "Widget Box" in err
    assert "Widget Factory" in err


def test_show_rich_format_renders_cycle_without_infinite_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = glossary_entry(0, "Alpha", "See Beta.")
    beta = glossary_entry(1, "Beta", "See Alpha.")
    compiled = FakeCompiledGlossaryCatalog(
        {
            alpha.definition: (glossary_span(1, "Beta", start=4),),
            beta.definition: (glossary_span(0, "Alpha", start=4),),
        }
    )
    resolved = resolved_glossary_project(entries=(alpha, beta), compiled=compiled)
    _patch_resolved(monkeypatch, resolved)
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=160)
    args = create_parser().parse_args(["glossary", "show", "Alpha"])

    cli_show.handle_glossary_show_command(args, console=console)

    text = output.getvalue()
    assert "2 terms · 1 requested · 1 related" in text
    assert 'mentioned as "Beta" in Alpha' in text
    assert "also mentioned by Beta" in text


def test_show_multiple_terms_are_both_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=160)
    args = create_parser().parse_args(["glossary", "show", "Gamma", "Alpha", "-d", "0"])

    cli_show.handle_glossary_show_command(args, console=console)

    text = output.getvalue()
    assert text.index("Gamma") < text.index("Alpha")
    assert text.count("REQUESTED") == 2


def test_show_exits_nonzero_on_project_resolution_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_resolve(*_a: object, **_kw: object) -> ResolvedGlossaryProject:
        raise GlossaryCliError("sase has no glossary configured")

    monkeypatch.setattr(cli_show, "resolve_glossary_cli_project", fake_resolve)
    args = create_parser().parse_args(["glossary", "show", "Alpha"])

    with pytest.raises(SystemExit) as exc:
        cli_show.handle_glossary_show_command(args)

    assert exc.value.code == 1
    assert "sase has no glossary configured" in capsys.readouterr().err
