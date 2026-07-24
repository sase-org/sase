"""CLI coverage for ``sase bead list``."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

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
        "sase bead list --limit 5",
        "sase bead list -n 0",
        "sase bead list --status=open",
        "sase bead list --status=claimed",
        "sase bead list --status=in_progress",
        "sase bead list --status=closed",
        "sase bead list --type=plan",
        "sase bead list --type=phase",
        "sase bead list --tier=epic",
        "sase bead list --tier=plan",
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
    assert args.limit == 2
    assert args.status == ["open", "closed"]
    assert args.tier == ["epic"]
    assert args.type == ["phase"]


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
