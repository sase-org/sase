"""Tests for ``sase snippet show``."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.main.parser import create_parser
from sase.snippet import cli_show
from sase.xprompt.models import XPrompt

from .snippet_cli_helpers import install_writable_snippet_project


def _console(output: StringIO) -> Console:
    return Console(file=output, force_terminal=False, color_system=None, width=160)


def test_show_rich_format_includes_raw_composed_sources_and_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    output = StringIO()
    args = create_parser().parse_args(["snippet", "show", "wrap", "-p", "demo"])

    cli_show.handle_snippet_show_command(args, console=_console(output))

    text = output.getvalue()
    assert "SNIPPET" in text
    assert "wrap" in text
    assert "RAW" in text
    assert "COMPOSED" in text
    assert "#[greet]$0" in text
    assert "CALLS" in text
    assert "greet" in text
    assert "writable" in text
    assert all(line == line.rstrip() for line in text.splitlines())


def test_show_maps_generated_alias_to_explicit_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    output = StringIO()
    args = create_parser().parse_args(["snippet", "show", "Greet", "-p", "demo"])

    cli_show.handle_snippet_show_command(args, console=_console(output))

    text = output.getvalue()
    assert "greet" in text
    assert "Greet" in text


def test_show_markdown_format_marks_authored_versus_derived(
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
    args = create_parser().parse_args(
        ["snippet", "show", "review", "-f", "markdown", "-p", "demo"]
    )

    cli_show.handle_snippet_show_command(args)

    text = capsys.readouterr().out
    assert "# review" in text
    assert "xprompt" in text
    assert "read-only" in text
    assert "xprompts/review.md" in text
    assert "```" in text


def test_show_json_field_names_and_ordering_are_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(
        ["snippet", "show", "wrap", "-f", "json", "-p", "demo"]
    )

    cli_show.handle_snippet_show_command(args)

    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert raw == json.dumps(payload, indent=2, sort_keys=True) + "\n"
    assert list(payload) == ["project", "reference", "snippet"]
    snippet = payload["snippet"]
    assert list(snippet) == [
        "aliases",
        "composed_template",
        "contributions",
        "diagnostics",
        "origin",
        "raw_template",
        "relations",
        "trigger",
    ]
    assert list(snippet["relations"]) == ["calls", "inbound", "outbound"]
    assert payload["project"] == "demo"
    assert payload["reference"] == "wrap"
    assert snippet["trigger"] == "wrap"
    assert snippet["raw_template"] == "#[greet]$0"
    assert snippet["relations"]["outbound"] == ["greet"]
    assert snippet["relations"]["calls"][0]["status"] == "resolved"
    assert snippet["origin"]["writable"] is True


def test_show_unknown_trigger_exits_with_lookup_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(tmp_path, monkeypatch)
    args = create_parser().parse_args(["snippet", "show", "xyzzy", "-p", "demo"])

    with pytest.raises(SystemExit) as exc:
        cli_show.handle_snippet_show_command(args)

    assert exc.value.code == 1
    assert "unknown snippet trigger: xyzzy" in capsys.readouterr().err


def test_show_ambiguous_prefix_exits_with_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_writable_snippet_project(
        tmp_path,
        monkeypatch,
        body=("ace:\n  snippets:\n    foo: |-\n      F$0\n    food: |-\n      D$0\n"),
    )
    args = create_parser().parse_args(["snippet", "show", "fo", "-p", "demo"])

    with pytest.raises(SystemExit) as exc:
        cli_show.handle_snippet_show_command(args)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "sase snippet show:" in err
    assert "did you mean" in err
    assert "foo" in err
    assert "food" in err
