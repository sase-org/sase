"""Tests for ``sase artifact link relation`` and link parser wiring.

Split from ``test_artifact_cli_link``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import argparse
import json

import pytest

from sase.artifact_cli.link_relations import handle_link_relation
from sase.main.parser import create_parser


def test_relation_show_prints_direction_and_examples(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        handle_link_relation(
            argparse.Namespace(relation_subcommand="show", slug="implements")
        )
        == 0
    )
    output = " ".join(capsys.readouterr().out.split())
    assert "implements" in output
    assert "implemented-by" in output
    assert "directed: yes" in output
    assert "written by: cli" in output
    assert "plan is the source, the bead is the target" in output
    assert "plan:" in output and "implements bead:" in output
    assert "bead:" in output and "implements plan:" in output
    assert "Recommended source kinds: plan" in output
    assert "Recommended target kinds: bead" in output


def test_relation_show_json_emits_full_registry_entry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        handle_link_relation(
            argparse.Namespace(
                relation_subcommand="show",
                slug="implements",
                json=True,
            )
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["slug"] == "implements"
    assert payload["inverse"] == "implemented-by"
    assert payload["directed"] is True
    assert payload["written_by"] == "cli"


def test_relation_show_unknown_slug_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        handle_link_relation(
            argparse.Namespace(relation_subcommand="show", slug="bogus")
        )
        == 1
    )
    assert "unknown relation" in capsys.readouterr().err


def test_relation_list_covers_every_builtin_slug(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        handle_link_relation(argparse.Namespace(relation_subcommand="list", json=True))
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    slugs = {item["slug"] for item in payload}
    assert slugs == {
        "awaits",
        "cites",
        "read",
        "related",
        "supersedes",
        "implements",
        "derives-from",
        "produced-by",
        "launched",
    }


def test_relation_dispatch_defaults_to_usage_without_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert handle_link_relation(argparse.Namespace()) == 2
    assert "relation {list,show}" in capsys.readouterr().err


def test_parser_link_relation_show_uses_positional() -> None:
    args = create_parser().parse_args(
        ["artifact", "link", "relation", "show", "implements"]
    )
    assert args.link_subcommand == "relation"
    assert args.relation_subcommand == "show"
    assert args.slug == "implements"


def test_parser_link_relation_bare_defaults_to_list() -> None:
    args = create_parser().parse_args(["artifact", "link", "relation"])
    assert args.link_subcommand == "relation"
    assert args.relation_subcommand == "list"


def test_parser_link_add_uses_positionals() -> None:
    args = create_parser().parse_args(
        [
            "artifact",
            "link",
            "add",
            "plan:a.md",
            "related",
            "plan:b.md",
            "shares a root cause",
        ]
    )
    assert args.link_subcommand == "add"
    assert args.source_ref == "plan:a.md"
    assert args.relation == "related"
    assert args.target_ref == "plan:b.md"
    assert args.why == "shares a root cause"


def test_parser_link_list_accepts_source() -> None:
    args = create_parser().parse_args(
        ["artifact", "link", "list", "--source", "store", "-j"]
    )
    assert args.link_subcommand == "list"
    assert args.source == "store"
