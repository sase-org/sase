"""Tests for the ``sase prompt`` command group (Phase 1: read-only CLI)."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.history.prompt import (
    PromptEntry,
    _save_prompt_history,
    compute_prompt_id,
)
from sase.main.parser import create_parser
from sase.prompt.cli_list import handle_prompt_list
from sase.prompt.cli_show import handle_prompt_show
from sase.prompt.cli_stats import handle_prompt_stats


@pytest.fixture
def history_file(tmp_path: Path) -> Iterator[Path]:
    """Point the prompt-history store at an isolated temp file."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        yield test_file


def _seed(*entries: PromptEntry) -> None:
    _save_prompt_history(list(entries))


def _entry(
    text: str,
    last_used: str,
    *,
    cancelled: bool = False,
) -> PromptEntry:
    return PromptEntry(
        text=text,
        timestamp=last_used,
        last_used=last_used,
        cancelled=cancelled,
    )


def _prompt_subparsers() -> dict[str, argparse.ArgumentParser]:
    parser = create_parser()
    top = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    prompt_parser = top.choices["prompt"]
    prompt_sub = next(
        action
        for action in prompt_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return dict(prompt_sub.choices)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_json_has_stable_shape_and_excludes_cancelled(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("launched prompt one", "260603_000000"),
        _entry("cancelled prompt two", "260605_000000", cancelled=True),
    )

    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=True)
    )

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert list(payload[0].keys()) == [
        "id",
        "timestamp",
        "last_used",
        "cancelled",
        "text_preview",
        "text_chars",
        "text_sha256",
    ]
    assert payload[0]["id"] == compute_prompt_id("launched prompt one")
    assert payload[0]["cancelled"] is False


def test_list_never_prints_full_long_prompt(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    long_text = "please " + "x" * 5000
    _seed(_entry(long_text, "260603_000000"))

    handle_prompt_list(
        argparse.Namespace(all=False, cancelled=False, query=None, limit=20, json=False)
    )

    out = capsys.readouterr().out
    assert "x" * 5000 not in out


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_show_raw_is_byte_exact(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "refactor the parser module to be cleaner"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=compute_prompt_id(text), format="raw"))

    # Exact text, no added or stripped trailing newline.
    assert capsys.readouterr().out == text


def test_show_raw_preserves_existing_trailing_newline(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "prompt with trailing newline\n"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=compute_prompt_id(text), format="raw"))

    assert capsys.readouterr().out == text


def test_show_markdown_has_metadata_header_and_body(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "do the important thing"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(
        argparse.Namespace(id=compute_prompt_id(text), format="markdown")
    )

    out = capsys.readouterr().out
    assert f"# Prompt {compute_prompt_id(text)}" in out
    assert "- cancelled: false" in out
    assert text in out


def test_show_json_includes_full_text(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "do the important thing"
    _seed(_entry(text, "260603_000000"))

    handle_prompt_show(argparse.Namespace(id=compute_prompt_id(text), format="json"))

    payload = json.loads(capsys.readouterr().out)
    assert payload["text"] == text
    assert payload["id"] == compute_prompt_id(text)


def test_show_unknown_selector_exits_nonzero(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("a stored prompt here", "260603_000000"))

    with pytest.raises(SystemExit) as exc_info:
        handle_prompt_show(argparse.Namespace(id="ph_ffffffffffff", format="raw"))

    assert exc_info.value.code == 2
    assert "No prompt matches selector" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def test_stats_json_has_stable_shape(
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("aaaa bbbb", "260601_000000"),
        _entry("cccc dddd eeee", "260603_000000"),
    )

    handle_prompt_stats(argparse.Namespace(json=True))

    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {
        "path",
        "exists",
        "size_bytes",
        "total",
        "launched",
        "cancelled",
        "oldest_last_used",
        "newest_last_used",
        "length_percentiles",
        "largest",
        "top_chips",
    }
    assert payload["total"] == 2
    assert set(payload["length_percentiles"]) == {"p50", "p90", "p99", "max"}


# ---------------------------------------------------------------------------
# parser / CLI contract
# ---------------------------------------------------------------------------


def test_prompt_subcommands_parse_with_short_flags() -> None:
    parser = create_parser()

    list_args = parser.parse_args(
        ["prompt", "list", "-a", "-c", "-j", "-l", "5", "-q", "auth"]
    )
    assert list_args.command == "prompt"
    assert list_args.prompt_subcommand == "list"
    assert list_args.all is True
    assert list_args.cancelled is True
    assert list_args.json is True
    assert list_args.limit == 5
    assert list_args.query == "auth"

    show_args = parser.parse_args(["prompt", "show", "ph_abc123", "-f", "markdown"])
    assert show_args.prompt_subcommand == "show"
    assert show_args.id == "ph_abc123"
    assert show_args.format == "markdown"

    stats_args = parser.parse_args(["prompt", "stats", "-j"])
    assert stats_args.prompt_subcommand == "stats"
    assert stats_args.json is True


def test_prompt_subcommands_are_sorted() -> None:
    assert list(_prompt_subparsers()) == sorted(_prompt_subparsers())


def test_prompt_public_long_options_have_short_aliases() -> None:
    for name, subparser in _prompt_subparsers().items():
        for action in subparser._actions:
            public_long_options = [
                option
                for option in action.option_strings
                if option.startswith("--") and option != "--help"
            ]
            if not public_long_options:
                continue
            short_options = [
                option
                for option in action.option_strings
                if option.startswith("-") and not option.startswith("--")
            ]
            assert short_options, f"prompt {name}: {'/'.join(public_long_options)}"
