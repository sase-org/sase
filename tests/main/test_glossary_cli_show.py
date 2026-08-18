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
    diamond_resolved_glossary_project,
    glossary_entry,
    glossary_span,
    resolved_glossary_project,
)


def _diamond_resolved() -> ResolvedGlossaryProject:
    return diamond_resolved_glossary_project()


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
    assert all(line == line.rstrip() for line in text.splitlines())


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
    assert "Use -d 0 to print only the requested terms." not in text


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


def test_show_multi_term_rich_marks_requested_and_prints_shared_related_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=160)
    args = create_parser().parse_args(["glossary", "show", "Alpha", "Gamma"])

    cli_show.handle_glossary_show_command(args, console=console)

    text = output.getvalue()
    assert text.count("REQUESTED") == 2
    assert text.index("● Alpha") < text.index("● Gamma")
    assert text.count("○ Delta") == 1
    assert text.count("○ Beta") == 1
    assert "4 terms · 2 requested · 2 related" in text
    assert all(line == line.rstrip() for line in text.splitlines())


def test_show_rich_wrapped_definition_has_no_trailing_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = glossary_entry(
        0,
        "Alpha",
        "A long definition that must wrap several times when rendered "
        "in a narrow console so wrap-padding cannot hide in short lines.",
    )
    resolved = resolved_glossary_project(entries=(entry,))
    _patch_resolved(monkeypatch, resolved)
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=48)
    args = create_parser().parse_args(["glossary", "show", "Alpha", "-d", "0"])

    cli_show.handle_glossary_show_command(args, console=console)

    text = output.getvalue()
    assert "long definition that must wrap" in text
    assert all(line == line.rstrip() for line in text.splitlines())


def test_show_rich_footer_is_only_actionable_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    default_out = StringIO()
    depth_zero_out = StringIO()
    leaf_out = StringIO()
    console_kw = {"force_terminal": False, "color_system": None, "width": 160}

    cli_show.handle_glossary_show_command(
        create_parser().parse_args(["glossary", "show", "Alpha"]),
        console=Console(file=default_out, **console_kw),
    )
    cli_show.handle_glossary_show_command(
        create_parser().parse_args(["glossary", "show", "Alpha", "-d", "0"]),
        console=Console(file=depth_zero_out, **console_kw),
    )
    cli_show.handle_glossary_show_command(
        create_parser().parse_args(["glossary", "show", "Delta"]),
        console=Console(file=leaf_out, **console_kw),
    )

    default_text = default_out.getvalue()
    depth_zero_text = depth_zero_out.getvalue()
    leaf_text = leaf_out.getvalue()
    hint = "Use -d 0 to print only the requested terms."
    assert hint in default_text
    assert hint not in depth_zero_text
    assert hint not in leaf_text
    assert "Related terms were printed" not in default_text
    assert "0 related" in leaf_text


def test_show_collapse_note_only_when_references_collapse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    collapsed_out = StringIO()
    clean_out = StringIO()
    console_kw = {"force_terminal": False, "color_system": None, "width": 160}

    cli_show.handle_glossary_show_command(
        create_parser().parse_args(["glossary", "show", "Beta", "B", "-d", "0"]),
        console=Console(file=collapsed_out, **console_kw),
    )
    cli_show.handle_glossary_show_command(
        create_parser().parse_args(["glossary", "show", "Alpha", "Gamma", "-d", "0"]),
        console=Console(file=clean_out, **console_kw),
    )

    collapsed = collapsed_out.getvalue()
    clean = clean_out.getvalue()
    note = "2 references resolved to 1 terms (duplicates and aliases collapsed)"
    assert note in collapsed
    assert "duplicates and aliases collapsed" not in clean


def test_show_json_multi_term_includes_requested_references(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    args = create_parser().parse_args(
        ["glossary", "show", "Alpha", "Gamma", "-f", "json"]
    )

    cli_show.handle_glossary_show_command(args)

    payload = json.loads(capsys.readouterr().out)
    requested = [
        node["term"] for node in payload["nodes"] if node["origin"] == "requested"
    ]
    assert requested == ["Alpha", "Gamma"]
    assert payload["requested_references"] == 2


def test_show_batch_unknown_term_writes_aggregate_error_and_no_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    args = create_parser().parse_args(["glossary", "show", "Alpha", "Zzz", "Qqq"])

    with pytest.raises(SystemExit) as exc:
        cli_show.handle_glossary_show_command(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "2 of 3 glossary references did not resolve:" in captured.err
    assert "Zzz — no close matches" in captured.err
    assert "Qqq — no close matches" in captured.err


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
