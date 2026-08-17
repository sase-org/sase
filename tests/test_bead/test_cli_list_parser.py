"""Argument parsing coverage for ``sase bead list``."""

from __future__ import annotations

import pytest

from tests.main.parser_cli_helpers import parse_sase_args


def test_list_parser_sets_filters_and_limit() -> None:
    args = parse_sase_args(
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
    assert args.color == "auto"
    assert args.format == "compact"
    assert args.limit == 2
    assert args.status == ["open", "closed"]
    assert args.tier == ["epic"]
    assert args.type == ["phase"]


def test_list_parser_accepts_color_choices() -> None:
    args = parse_sase_args(["bead", "list", "--color", "never"])

    assert args.color == "never"


@pytest.mark.parametrize("flag", ["--format", "-f"])
def test_list_parser_accepts_format_aliases(flag: str) -> None:
    args = parse_sase_args(["bead", "list", flag, "json"])

    assert args.format == "json"


def test_list_parser_defaults_to_compact_for_explicit_and_bare_list() -> None:
    assert parse_sase_args(["bead", "list"]).format == "compact"
    assert parse_sase_args(["bead"]).format == "compact"


def test_list_parser_rejects_unknown_format() -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_sase_args(["bead", "list", "-f", "bogus"])

    assert excinfo.value.code == 2


def test_list_parser_accepts_short_limit_and_zero() -> None:
    args = parse_sase_args(["bead", "list", "-n", "0"])

    assert args.limit == 0


def test_list_parser_accepts_created_date_filters_and_status_all() -> None:
    args = parse_sase_args(
        [
            "bead",
            "list",
            "--since",
            "1w",
            "--until",
            "today",
            "--status",
            "all",
        ]
    )
    short_args = parse_sase_args(["bead", "list", "-S", "1w", "-u", "today"])

    assert args.since == "1w"
    assert args.until == "today"
    assert args.status == ["all"]
    assert short_args.since == "1w"
    assert short_args.until == "today"


def test_list_parser_rejects_malformed_created_date(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_sase_args(["bead", "list", "--since", "lastweek"])

    assert excinfo.value.code == 2
    assert "Invalid DATE 'lastweek'" in capsys.readouterr().err


def test_list_parser_rejects_negative_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_sase_args(["bead", "list", "--limit", "-1"])

    assert excinfo.value.code == 2
    assert "must be a non-negative integer" in capsys.readouterr().err
