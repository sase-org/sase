"""Tests for ``sase glossary all``."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from rich.console import Console

from sase.glossary import cli_all
from sase.glossary.cli_common import GlossaryCliError, ResolvedGlossaryProject
from sase.main.parser import create_parser

from .glossary_cli_helpers import (
    diamond_resolved_glossary_project,
    glossary_entry,
    resolved_glossary_project,
)

_AUDIT_HINT = (
    'Not an audited read — agents must use: sase glossary read <term> -r "<why>"'
)


def _diamond_resolved() -> ResolvedGlossaryProject:
    return diamond_resolved_glossary_project()


def _patch_resolved(
    monkeypatch: pytest.MonkeyPatch, resolved: ResolvedGlossaryProject
) -> None:
    monkeypatch.setattr(
        cli_all, "resolve_glossary_cli_project", lambda *_a, **_kw: resolved
    )


def _rich_console(output: StringIO, *, width: int = 160) -> Console:
    return Console(file=output, force_terminal=False, color_system=None, width=width)


def _section_keys(text: str) -> list[str]:
    keys: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        first = stripped[0]
        rest = stripped[1:].strip()
        if (first == "#" or first.isalpha()) and rest and all(ch == "─" for ch in rest):
            keys.append(first)
    return keys


def test_all_rich_format_prints_catalog_without_closure_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    output = StringIO()
    args = create_parser().parse_args(["glossary", "all"])

    cli_all.handle_glossary_all_command(args, console=_rich_console(output))

    text = output.getvalue()
    assert "GLOSSARY  sase" in text
    assert "4 terms" in text
    assert "● Alpha" in text
    assert "● Beta" in text
    assert "● Gamma" in text
    assert "● Delta" in text
    assert "REQUESTED" not in text
    assert "RELATED" not in text
    assert "aka B" in text
    delta_pos = text.index("● Delta")
    gamma_pos = text.index("● Gamma")
    backlink_pos = text.index("referenced by Beta, Gamma")
    assert delta_pos < backlink_pos < gamma_pos
    beta_pos = text.index("● Beta")
    aka_pos = text.index("aka B")
    assert beta_pos < aka_pos < delta_pos
    assert _AUDIT_HINT in text
    assert all(line == line.rstrip() for line in text.splitlines())


def test_all_rich_letter_sections_emit_one_rule_per_letter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = resolved_glossary_project(
        entries=(
            glossary_entry(0, "Alpha", "First letter."),
            glossary_entry(1, "Zeta", "Later letter."),
        )
    )
    _patch_resolved(monkeypatch, resolved)
    output = StringIO()
    args = create_parser().parse_args(["glossary", "all"])

    cli_all.handle_glossary_all_command(args, console=_rich_console(output))

    assert _section_keys(output.getvalue()) == ["A", "Z"]


def test_all_rich_non_letter_terms_group_under_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = resolved_glossary_project(
        entries=(
            glossary_entry(0, "Alpha", "A letter."),
            glossary_entry(1, "42 Widget", "A numbered widget."),
        )
    )
    _patch_resolved(monkeypatch, resolved)
    output = StringIO()
    args = create_parser().parse_args(["glossary", "all"])

    cli_all.handle_glossary_all_command(args, console=_rich_console(output))

    text = output.getvalue()
    assert _section_keys(text) == ["#", "A"]
    assert text.index("● 42 Widget") < text.index("● Alpha")


def test_all_prints_entries_alphabetically_regardless_of_catalog_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diamond = _diamond_resolved()
    shuffled = resolved_glossary_project(
        entries=(
            diamond.catalog.entries[3],
            diamond.catalog.entries[0],
            diamond.catalog.entries[2],
            diamond.catalog.entries[1],
        ),
        compiled=diamond.compiled,
    )
    _patch_resolved(monkeypatch, shuffled)
    output = StringIO()
    args = create_parser().parse_args(["glossary", "all"])

    cli_all.handle_glossary_all_command(args, console=_rich_console(output))

    text = output.getvalue()
    assert (
        text.index("● Alpha")
        < text.index("● Beta")
        < text.index("● Delta")
        < text.index("● Gamma")
    )


def test_all_markdown_format_uses_flat_headings_and_backlinks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    args = create_parser().parse_args(["glossary", "all", "-f", "markdown"])

    cli_all.handle_glossary_all_command(args)

    text = capsys.readouterr().out
    assert "# Alpha" in text
    assert "# Beta" in text
    assert "# Gamma" in text
    assert "# Delta" in text
    assert "referenced by Beta, Gamma" in text
    assert "*Requested*" not in text
    assert "## " not in text


def test_all_json_format_is_catalog_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_resolved(monkeypatch, _diamond_resolved())
    args = create_parser().parse_args(["glossary", "all", "-f", "json"])

    cli_all.handle_glossary_all_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "count": 4,
        "project": "sase",
        "terms": [
            {
                "aliases": [],
                "definition": "Mentions Beta then Gamma.",
                "reference_terms": ["Beta", "Gamma"],
                "referenced_by": [],
                "source": {"config_path": "sase/sase.yml"},
                "term": "Alpha",
            },
            {
                "aliases": ["B"],
                "definition": "Mentions Delta.",
                "reference_terms": ["Delta"],
                "referenced_by": ["Alpha"],
                "source": {"config_path": "sase/sase.yml"},
                "term": "Beta",
            },
            {
                "aliases": [],
                "definition": "A leaf.",
                "reference_terms": [],
                "referenced_by": ["Beta", "Gamma"],
                "source": {"config_path": "sase/sase.yml"},
                "term": "Delta",
            },
            {
                "aliases": [],
                "definition": "Mentions Delta.",
                "reference_terms": ["Delta"],
                "referenced_by": ["Alpha"],
                "source": {"config_path": "sase/sase.yml"},
                "term": "Gamma",
            },
        ],
    }
    by_term = {term["term"]: term for term in payload["terms"]}
    assert by_term["Alpha"]["reference_terms"] == ["Beta", "Gamma"]
    assert by_term["Delta"]["referenced_by"] == ["Beta", "Gamma"]


def test_all_empty_catalog_rich_prints_message_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch, resolved_glossary_project(entries=()))
    output = StringIO()
    args = create_parser().parse_args(["glossary", "all"])

    cli_all.handle_glossary_all_command(args, console=_rich_console(output))

    text = output.getvalue()
    assert text.strip() == "no glossary terms configured for sase"
    assert "GLOSSARY" not in text
    assert "Not an audited read" not in text


def test_all_empty_catalog_json_is_zero_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_resolved(monkeypatch, resolved_glossary_project(entries=()))
    args = create_parser().parse_args(["glossary", "all", "-f", "json"])

    cli_all.handle_glossary_all_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"count": 0, "project": "sase", "terms": []}


def test_all_empty_catalog_markdown_is_header_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_resolved(monkeypatch, resolved_glossary_project(entries=()))
    args = create_parser().parse_args(["glossary", "all", "-f", "markdown"])

    cli_all.handle_glossary_all_command(args)

    text = capsys.readouterr().out
    assert text.strip() == "GLOSSARY: sase"
    assert "#" not in text.replace("GLOSSARY:", "")


def test_all_exits_nonzero_on_project_resolution_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_resolve(*_a: object, **_kw: object) -> ResolvedGlossaryProject:
        raise GlossaryCliError("sase has no glossary configured")

    monkeypatch.setattr(cli_all, "resolve_glossary_cli_project", fake_resolve)
    args = create_parser().parse_args(["glossary", "all"])

    with pytest.raises(SystemExit) as exc:
        cli_all.handle_glossary_all_command(args)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("sase glossary all: ")
    assert "sase has no glossary configured" in err
