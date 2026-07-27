"""CLI coverage for ``sase bead search``."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


def test_search_skill_examples_parse_against_cli_contract() -> None:
    source_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "sase"
        / "xprompts"
        / "skills"
        / "sase_beads.md"
    )
    source = source_path.read_text(encoding="utf-8")
    search_section = source.split("### search", 1)[1].split("### ready", 1)[0]
    examples = [
        line.strip()
        for line in search_section.splitlines()
        if line.strip().startswith("sase bead search ")
    ]

    assert examples == [
        "sase bead search auth",
        "sase bead search auth --format full --limit 3",
        "sase bead search auth --status open --type phase",
    ]

    parser = create_parser()
    for example in examples:
        argv = shlex.split(example)
        args = parser.parse_args(argv[1:])
        assert args.command == "bead"
        assert args.bead_subcommand == "search"
        assert args.query == "auth"


def test_search_parser_sets_query_filters_and_output_options() -> None:
    args = create_parser().parse_args(
        [
            "bead",
            "search",
            "Needle",
            "--color",
            "never",
            "--format",
            "json",
            "--limit",
            "2",
            "--status",
            "open",
            "--status",
            "closed",
            "--tier",
            "epic",
            "--type",
            "phase",
        ]
    )

    assert args.command == "bead"
    assert args.bead_subcommand == "search"
    assert args.query == "Needle"
    assert args.color == "never"
    assert args.format == "json"
    assert args.limit == 2
    assert args.status == ["open", "closed"]
    assert args.tier == ["epic"]
    assert args.type == ["phase"]


def test_search_parser_rejects_negative_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "search", "needle", "--limit", "-1"])

    assert excinfo.value.code == 2
    assert "must be a non-negative integer" in capsys.readouterr().err


def test_handle_bead_search_compact_includes_closed_and_match_reason(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create(
            "Needle Epic",
            IssueType.PLAN,
            description="Needle in description",
        )
        proj.create("Notes Carrier", IssueType.PLAN, notes="private needle note")
        closed = proj.create("Closed Needle", IssueType.PLAN)
        proj.close([closed.id], reason="done")

    args = create_parser().parse_args(["bead", "search", "needle"])
    bead_cli.handle_bead_search(args)

    out = capsys.readouterr().out
    assert "○" in out
    assert "Needle Epic" in out
    assert "Needle in description" in out
    assert 'notes: "private needle note"' in out
    assert "✓" in out
    assert "Closed Needle" in out


def test_handle_bead_search_compact_snippet_uses_matching_line(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create(
            "Multiline Description",
            IssueType.PLAN,
            description="Overview line\nNeedle appears later",
        )

    args = create_parser().parse_args(["bead", "search", "needle"])
    bead_cli.handle_bead_search(args)

    out = capsys.readouterr().out
    assert "Multiline Description" in out
    assert "Needle appears later" in out
    assert "Overview line" not in out


def test_handle_bead_search_json_outputs_envelope(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Needle Epic", IssueType.PLAN)

    args = create_parser().parse_args(["bead", "search", "needle", "--format", "json"])
    bead_cli.handle_bead_search(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "needle"
    assert payload["count"] == 1
    assert payload["results"][0]["issue"]["id"] == issue.id
    assert payload["results"][0]["matched_fields"] == ["title"]


def test_handle_bead_search_full_reuses_show_rendering(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Needle Epic", IssueType.PLAN, description="Full body")

    args = create_parser().parse_args(["bead", "search", "needle", "--format", "full"])
    bead_cli.handle_bead_search(args)
    search_out = capsys.readouterr().out

    bead_cli.handle_bead_show(create_parser().parse_args(["bead", "show", issue.id]))
    show_out = capsys.readouterr().out

    assert search_out == show_out


def test_handle_bead_search_no_matches_is_success(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create("Present", IssueType.PLAN)

    args = create_parser().parse_args(["bead", "search", "missing"])
    bead_cli.handle_bead_search(args)

    assert capsys.readouterr().out == 'No beads match "missing".\n'


def test_handle_bead_search_whitespace_query_exits_usage_error(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["bead", "search", "   "])

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_search(args)

    assert excinfo.value.code == 2
    assert capsys.readouterr().err == "Error: search query cannot be empty\n"
