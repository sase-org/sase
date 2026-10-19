"""Parser tests for ``sase stats`` and ``sase stats project``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from sase.main.parser import default_list_delegation_notice
from sase.stats.registry import PROJECT_REPORT_GROUPINGS, PROJECT_REPORT_LEGENDS
from tests.main.parser_cli_helpers import parse_sase_args
from tests.main.parser_help_helpers import (
    assert_metavar_option_documented,
    parse_and_capture_help,
    parser_for,
)

GOLDEN = Path(__file__).resolve().parents[1] / "stats" / "golden" / "cli"
_UPDATE = os.environ.get("SASE_UPDATE_PROJECT_RENDER_GOLDENS") == "1"
# Python 3.13 argparse stopped repeating an option's metavar after its short
# alias ("-f, --format {…}" rather than "-f {…}, --format {…}"), which also
# moves short invocations onto the help column. 3.13 and 3.14 render this
# parser identically, so one golden per spelling covers requires-python.
_HELP_GOLDEN = (
    "project_help_py313.txt" if sys.version_info >= (3, 13) else "project_help.txt"
)


def test_bare_stats_is_not_a_list_default() -> None:
    args = parse_sase_args(["stats"])

    assert args.command == "stats"
    assert args.stats_subcommand is None
    assert default_list_delegation_notice(args) is None


def test_unknown_view_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as error:
        parse_sase_args(["stats", "overview"])

    assert error.value.code == 2


def test_project_options_parse() -> None:
    args = parse_sase_args(
        [
            "stats",
            "project",
            "-D",
            "-F",
            "-f",
            "markdown",
            "-g",
            "repo",
            "-p",
            "sase",
            "-p",
            "+bob",
            "-r",
            "30d",
        ]
    )

    assert args.stats_subcommand == "project"
    assert args.include_disabled is True
    assert args.fetch is True
    assert args.format == "markdown"
    assert args.group_by == "repo"
    assert args.json is False
    assert args.project == ["sase", "+bob"]
    assert args.range == "30d"


def test_json_shorthand_parses() -> None:
    args = parse_sase_args(["stats", "project", "-j"])

    assert args.json is True
    assert args.format is None


def test_project_options_are_sorted_with_short_aliases() -> None:
    parser = parser_for(("sase", "stats", "project"))
    shorts: list[str] = []
    for action in parser._actions:
        if not action.option_strings or "--help" in action.option_strings:
            continue
        short = [
            opt
            for opt in action.option_strings
            if opt.startswith("-") and not opt.startswith("--")
        ]
        long = [opt for opt in action.option_strings if opt.startswith("--")]
        assert short, action.option_strings
        assert long, action.option_strings
        shorts.append(short[0])

    assert shorts == sorted(shorts)
    assert shorts == ["-D", "-F", "-f", "-g", "-j", "-p", "-r"]


def test_group_by_choices_match_registry() -> None:
    parser = parser_for(("sase", "stats", "project"))
    action = next(
        item for item in parser._actions if "--group-by" in item.option_strings
    )

    assert tuple(action.choices or ()) == tuple(sorted(PROJECT_REPORT_GROUPINGS))


def test_project_help_golden(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("PYTHON_COLORS", raising=False)
    help_text = parse_and_capture_help(["stats", "project", "-h"], capsys)
    path = GOLDEN / _HELP_GOLDEN
    if _UPDATE:
        # Update mode rewrites only the running interpreter's golden.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(help_text, encoding="utf-8")
        return
    assert help_text == path.read_text(encoding="utf-8")


def test_project_help_includes_definitions_and_examples(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("PYTHON_COLORS", raising=False)
    help_text = parse_and_capture_help(["stats", "project", "-h"], capsys)

    assert "definitions:" in help_text
    for entry in PROJECT_REPORT_LEGENDS:
        assert entry.term in help_text
        assert entry.meaning in help_text
    assert "sase stats project -p sase -r all" in help_text
    assert "-D, --include-disabled" in help_text
    assert "-F, --fetch" in help_text
    assert_metavar_option_documented(
        help_text, "-f", "--format", "{json,markdown,rich}"
    )
    assert_metavar_option_documented(
        help_text, "-g", "--group-by", "{model,patch,project,repo}"
    )
    assert "-j, --json" in help_text
    assert_metavar_option_documented(help_text, "-p", "--project", "PROJECT")
    assert_metavar_option_documented(help_text, "-r", "--range", "RANGE")
