"""Parser tests for ``sase var show`` and historical ``sase var list``."""

from __future__ import annotations

import pytest

from sase.main.parser import create_parser


def test_parser_registers_var_show_and_list_aliases() -> None:
    parser = create_parser()

    show = parser.parse_args(
        ["var", "show", "build", "-f", "json", "-c", "never", "-p", "sase"]
    )
    listing = parser.parse_args(
        [
            "var",
            "list",
            "-a",
            "build.*",
            "-k",
            "status*",
            "-n",
            "10:2",
            "-p",
            "sase",
            "-H",
            "-r",
            "-s",
            "1w",
            "-u",
            "today",
            "-v",
            "ok",
        ]
    )

    assert show.var_subcommand == "show"
    assert show.agent_name == "build"
    assert show.format == "json"
    assert show.color == "never"
    assert show.project == "sase"
    assert listing.var_subcommand == "list"
    assert listing.agents == ["build.*"]
    assert listing.keys == ["status*"]
    assert listing.limit == (10, 2)
    assert listing.projects == ["sase"]
    assert listing.hidden is True
    assert listing.reverse is True
    assert listing.since == "1w"
    assert listing.until == "today"
    assert listing.values == ["ok"]
    assert listing.value_json is None


def test_parser_single_limit_keeps_default_value_limit() -> None:
    args = create_parser().parse_args(["var", "list", "--limit", "0"])

    assert args.limit == (0, 5)


@pytest.mark.parametrize("raw", ["-1", "20:", ":5", "nope", "1:x"])
def test_parser_rejects_invalid_limits(raw: str) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "list", "--limit", raw])

    assert exc.value.code == 2


def test_parse_var_list_limit_zero_is_unlimited() -> None:
    assert create_parser().parse_args(["var", "list", "--limit", "0:0"]).limit == (
        0,
        0,
    )
    assert create_parser().parse_args(["var", "list", "--limit", "8"]).limit == (
        8,
        5,
    )


def test_parser_rejects_invalid_date_bounds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "list", "--since", "next-week"])

    assert exc.value.code == 2
    assert "Invalid DATE" in capsys.readouterr().err


def test_parser_rejects_invalid_value_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "list", "--value-json", "{"])

    assert exc.value.code == 2
    assert "invalid JSON" in capsys.readouterr().err


def test_parser_value_and_value_json_are_mutually_exclusive() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "list", "--value", "ok", "--value-json", '"ok"'])

    assert exc.value.code == 2


def test_parse_var_value_json_normalizes_typed_values() -> None:
    args = create_parser().parse_args(
        ["var", "list", "--value-json", '{"z":1,"a":true}']
    )

    assert args.value_json == [{"a": True, "z": 1}]


def test_var_list_and_show_help_keep_options_alphabetized(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "list", "--help"])
    assert exc.value.code == 0
    list_help = capsys.readouterr().out
    assert list_help.index(", --agent") < list_help.index(", --color")
    assert list_help.index(", --color") < list_help.index(", --format")
    assert list_help.index(", --format") < list_help.index(", --hidden")
    assert list_help.index(", --hidden") < list_help.index(", --key")
    assert list_help.index(", --key") < list_help.index(", --limit")
    assert list_help.index(", --limit") < list_help.index(", --project")
    assert list_help.index(", --project") < list_help.index(", --reverse")
    assert list_help.index(", --reverse") < list_help.index(", --since")
    assert list_help.index(", --since") < list_help.index(", --until")
    assert list_help.index(", --until") < list_help.index(", --value ")
    assert list_help.index(", --value ") < list_help.index(", --value-json")

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "show", "--help"])
    assert exc.value.code == 0
    show_help = capsys.readouterr().out
    assert show_help.index(", --color") < show_help.index(", --format")
    assert show_help.index(", --format") < show_help.index(", --project")
