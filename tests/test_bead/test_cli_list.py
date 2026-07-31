"""CLI coverage for ``sase bead list``."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


def test_list_skill_examples_parse_against_cli_contract() -> None:
    source_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "sase"
        / "xprompts"
        / "skills"
        / "sase_beads.md"
    )
    source = source_path.read_text(encoding="utf-8")
    list_section = source.split("### list", 1)[1].split("### search", 1)[0]
    examples = [
        line.strip()
        for line in list_section.splitlines()
        if line.strip().startswith("sase bead list")
    ]

    assert examples == [
        "sase bead list",
        "sase bead list --format json",
        "sase bead list --format full --limit 3",
        "sase bead list --status ready --type task",
        "sase bead list --status open --type phase",
        "sase bead list --tier epic",
        "sase bead list --status closed --limit 0",
    ]

    parser = create_parser()
    for example in examples:
        argv = shlex.split(example)
        args = parser.parse_args(argv[1:])
        assert args.command == "bead"
        assert args.bead_subcommand == "list"


def test_list_parser_sets_filters_and_limit() -> None:
    args = create_parser().parse_args(
        [
            "bead",
            "list",
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
    assert args.bead_subcommand == "list"
    assert args.format == "compact"
    assert args.limit == 2
    assert args.status == ["open", "closed"]
    assert args.tier == ["epic"]
    assert args.type == ["phase"]


@pytest.mark.parametrize("flag", ["--format", "-f"])
def test_list_parser_accepts_format_aliases(flag: str) -> None:
    args = create_parser().parse_args(["bead", "list", flag, "json"])

    assert args.format == "json"


def test_list_parser_defaults_to_compact_for_explicit_and_bare_list() -> None:
    parser = create_parser()

    assert parser.parse_args(["bead", "list"]).format == "compact"
    assert parser.parse_args(["bead"]).format == "compact"


def test_list_parser_rejects_unknown_format() -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "list", "-f", "bogus"])

    assert excinfo.value.code == 2


def test_list_parser_accepts_short_limit_and_zero() -> None:
    args = create_parser().parse_args(["bead", "list", "-n", "0"])

    assert args.limit == 0


def test_list_parser_rejects_negative_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "list", "--limit", "-1"])

    assert excinfo.value.code == 2
    assert "must be a non-negative integer" in capsys.readouterr().err


def test_handle_bead_list_json_outputs_envelope(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Open Epic", IssueType.PLAN)

    args = create_parser().parse_args(["bead", "list", "-f", "json"])
    bead_cli.handle_bead_list(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["total"] == 1
    assert payload["statuses"] == ["open", "claimed", "ready", "in_progress"]
    assert payload["implied_status_closed"] is False
    assert payload["results"][0]["id"] == issue.id
    assert payload["results"][0]["resolution"] is None


def test_handle_bead_list_json_empty_store_is_valid_envelope(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["bead", "list", "--format", "json"])
    bead_cli.handle_bead_list(args)

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["count"] == 0
    assert payload["total"] == 0
    assert payload["implied_status_closed"] is False
    assert payload["results"] == []
    assert "No issues found." not in output


def test_handle_bead_list_json_reports_implicit_closed_without_notice(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Closed Epic", IssueType.PLAN)
        proj.close([issue.id], reason="done")

    args = create_parser().parse_args(["bead", "list", "-f", "json"])
    bead_cli.handle_bead_list(args)

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["statuses"] == ["closed"]
    assert payload["implied_status_closed"] is True
    assert payload["results"][0]["id"] == issue.id
    assert payload["results"][0]["resolution"] == "done"
    assert "No open beads to show" not in output


def test_handle_bead_list_json_limit_preserves_total(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create("First Epic", IssueType.PLAN)
        proj.create("Second Epic", IssueType.PLAN)

    args = create_parser().parse_args(["bead", "list", "-f", "json", "--limit", "1"])
    bead_cli.handle_bead_list(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["total"] == 2


def test_handle_bead_list_full_reuses_show_rendering(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create(
            "Full Epic",
            IssueType.PLAN,
            description="Full body",
        )

    args = create_parser().parse_args(["bead", "list", "-f", "full"])
    bead_cli.handle_bead_list(args)
    list_out = capsys.readouterr().out

    bead_cli.handle_bead_show(create_parser().parse_args(["bead", "show", issue.id]))
    show_out = capsys.readouterr().out

    assert list_out == show_out


def test_handle_bead_list_explicit_compact_matches_default(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create("Compact Epic", IssueType.PLAN)

    bead_cli.handle_bead_list(create_parser().parse_args(["bead", "list"]))
    default_out = capsys.readouterr().out

    bead_cli.handle_bead_list(
        create_parser().parse_args(["bead", "list", "--format", "compact"])
    )
    explicit_out = capsys.readouterr().out

    assert explicit_out == default_out
