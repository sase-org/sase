from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from sase.agents.cli_search import handle_agents_search
from sase.main.parser import create_parser
from tests._agent_search_cli_helpers import patch_sources, make_row, make_snapshot
from tests.main.parser_help_helpers import help_subcommand_rows, parser_for


def test_agent_search_parser_and_help_are_complete_and_sorted() -> None:
    parser = create_parser(only="agent")
    args = parser.parse_args(
        [
            "agent",
            "search",
            "-j",
            "-l",
            "5",
            "-p",
            "sase",
            "revivable:true",
            "AND",
            "role:code",
        ]
    )

    assert args.agent_subcommand == "search"
    assert args.json is True
    assert args.limit == 5
    assert args.project == "sase"
    assert args.query == ["revivable:true", "AND", "role:code"]

    expected_commands = {
        "archive",
        "artifacts",
        "drain",
        "index",
        "kill",
        "list",
        "names",
        "persist-cleanup",
        "persist-directive",
        "prompts",
        "restart",
        "revert",
        "search",
        "show",
        "sync",
        "tribe",
        "wait",
    }
    agent_help = parser_for(("sase", "agent")).format_help()
    assert help_subcommand_rows(agent_help, expected_commands) == sorted(
        expected_commands
    )

    search_help = parser_for(("sase", "agent", "search")).format_help()
    assert "-j" in search_help
    assert "--json" in search_help
    assert "-l LIMIT" in search_help
    assert "--limit LIMIT" in search_help
    assert "-p PROJECT" in search_help
    assert "--project PROJECT" in search_help
    assert "revivable:true AND project:sase AND role:code" in search_help
    assert "linked:true AND relation:read" in search_help
    assert "in:archive AND outcome:failed" in search_help
    assert "in:inbox" in search_help
    assert "Nm means months" in search_help
    assert "Nm means minutes" in search_help


def test_agent_search_parser_accepts_options_before_and_after_query() -> None:
    parser = create_parser(only="agent")
    before = parser.parse_args(
        ["agent", "search", "-j", "-l", "5", "-p", "sase", "kind:session"]
    )
    after = parser.parse_args(
        ["agent", "search", "kind:session", "-j", "-l", "5", "-p", "sase"]
    )
    interleaved = parser.parse_args(
        ["agent", "search", "kind:session", "-l", "5", "-p", "sase", "-j"]
    )

    for args in (before, after, interleaved):
        assert args.json is True
        assert args.limit == 5
        assert args.project == "sase"
        assert args.query == ["kind:session"]


def test_agent_search_boolean_dialect_has_no_leading_dash_spelling() -> None:
    """The boolean dialect negates with ``NOT``, never a leading ``-``, so
    ``nargs="*"`` swallowing a lone ``-foo`` token as an unrecognized option is
    expected: there is no real query a user would need ``--`` to escape."""
    parser = create_parser(only="agent")

    with pytest.raises(SystemExit):
        parser.parse_args(["agent", "search", "-foo"])


def test_agent_search_handles_options_parsed_after_the_query(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    snapshot = make_snapshot(make_row("visible", kind=("session",)))
    patch_sources(monkeypatch, snapshot)
    parser = create_parser(only="agent")

    args = parser.parse_args(
        ["agent", "search", "kind:session", "-j", "-l", "5", "-p", "sase"]
    )
    code = handle_agents_search(args)

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in payload] == ["visible"]


def test_agent_search_query_followed_by_limit_flag_does_not_hit_tokenizer_error(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Regression test for a REMAINDER-nargs bug: ``-l 3`` after the query used to
    be swallowed into the query text and reach the tokenizer as literal characters."""
    snapshot = make_snapshot(make_row("visible", kind=("session",)))
    patch_sources(monkeypatch, snapshot)
    parser = create_parser(only="agent")

    args = parser.parse_args(["agent", "search", "kind:session", "-l", "3"])
    code = handle_agents_search(args)

    assert code == 0
    output = capsys.readouterr().out
    assert "error" not in output.lower()
    assert "visible" in output
