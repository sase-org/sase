"""Parser tests for ``sase var get`` and historical ``sase var list``."""

from __future__ import annotations

import pytest

from sase.core.agent_output_variable_selector_wire import (
    DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT,
    OutputVariableSelectorWire,
)
from sase.main.parser import create_parser, default_list_delegation_notice
from sase.main.parser_var import WrappedAgentTarget


def test_parser_registers_var_get_aliases() -> None:
    parser = create_parser()

    args = parser.parse_args(
        [
            "var",
            "get",
            "status",
            "build.status",
            "-f",
            "raw",
            "-c",
            "never",
            "-p",
            "sase",
            "-H",
            "-n",
            "0",
        ]
    )

    assert args.var_subcommand == "get"
    assert [target.raw for target in args.targets] == [
        "status",
        "build.status",
    ]
    assert isinstance(args.targets[0], OutputVariableSelectorWire)
    assert args.targets[0].key == "status"
    assert args.targets[1].scope.kind == "exact"
    assert args.targets[1].scope.name == "build"
    assert args.format == "raw"
    assert args.color == "never"
    assert args.projects == ["sase"]
    assert args.hidden is True
    assert args.limit == 0
    assert args.limit_explicit is True


def test_parser_accepts_zero_target_and_wrapped_agent_get() -> None:
    parser = create_parser()

    empty = parser.parse_args(["var", "get", "--format", "json"])
    wrapped = parser.parse_args(
        ["var", "get", "<build>", "-f", "json", "-c", "never", "-p", "sase", "-H"]
    )
    dotted = parser.parse_args(["var", "get", "<research.final>"])
    hyphenated = parser.parse_args(["var", "get", "<foo-bar>"])
    digit = parser.parse_args(["var", "get", "<2review>"])

    assert empty.var_subcommand == "get"
    assert empty.targets == []
    assert empty.format == "json"
    assert empty.limit == DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT
    assert empty.limit_explicit is False
    assert wrapped.targets[0] == WrappedAgentTarget(raw="<build>", agent_name="build")
    assert wrapped.format == "json"
    assert wrapped.color == "never"
    assert wrapped.projects == ["sase"]
    assert wrapped.hidden is True
    assert wrapped.limit_explicit is False
    assert dotted.targets[0].agent_name == "research.final"
    assert hyphenated.targets[0].agent_name == "foo-bar"
    assert digit.targets[0].agent_name == "2review"


def test_parser_registers_var_list_aliases() -> None:
    parser = create_parser()

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


def test_parser_rejects_removed_var_show(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "show"])

    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


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


def test_parser_rejects_invalid_get_selectors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "get", "report[summary]"])

    assert exc.value.code == 2
    assert "invalid selector" in capsys.readouterr().err


@pytest.mark.parametrize("raw", ["<>", "<   >", "<build", "build>"])
def test_parser_rejects_malformed_wrapped_agents(
    raw: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "get", raw])

    assert exc.value.code == 2
    assert "wrapped agent name" in capsys.readouterr().err


def test_parser_rejects_mixed_and_multiple_wrapped_targets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "get", "<build>", "status"])
    assert exc.value.code == 2
    assert "cannot mix" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "get", "<build>", "<review>"])
    assert exc.value.code == 2
    assert "only one wrapped" in capsys.readouterr().err


def test_parser_rejects_invalid_get_limit() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "get", "status", "--limit", "-1"])

    assert exc.value.code == 2


def test_var_list_and_get_help_keep_options_alphabetized(
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
        parser.parse_args(["var", "get", "--help"])
    assert exc.value.code == 0
    get_help = capsys.readouterr().out
    assert get_help.index(", --color") < get_help.index(", --format")
    assert get_help.index(", --format") < get_help.index(", --hidden")
    assert get_help.index(", --hidden") < get_help.index(", --limit")
    assert get_help.index(", --limit") < get_help.index(", --project")
    assert "sase var get" in get_help
    assert "sase var get '<build>' --format json" in get_help
    assert "sase var get status" in get_help
    assert "sase var get build.status --format raw" in get_help
    assert "sase var get build.*" in get_help
    assert "quote" in get_help.lower() or "quoted" in get_help.lower()


def test_parser_registers_var_set_assignments() -> None:
    parser = create_parser()

    args = parser.parse_args(["var", "set", "plan_file=sdd/plan.md", "status=ok"])

    assert args.command == "var"
    assert args.var_subcommand == "set"
    assert args.assignments == ["plan_file=sdd/plan.md", "status=ok"]


def test_parser_registers_json_for_var_set() -> None:
    parser = create_parser()

    set_args = parser.parse_args(["var", "set", "cfg={}", "--json"])

    assert set_args.var_subcommand == "set"
    assert set_args.json is True


def test_bare_var_delegates_to_list() -> None:
    args = create_parser().parse_args(["var"])
    explicit = create_parser().parse_args(["var", "list"])

    assert args.var_subcommand == "list"
    assert args.format == "pretty"
    assert args.limit == explicit.limit
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase var'; delegating to 'sase var list'."
    )


def test_var_help_keeps_subcommands_and_set_options_alphabetized(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "--help"])
    assert exc.value.code == 0
    group_help = capsys.readouterr().out
    assert group_help.index("\n    get ") < group_help.index("\n    list ")
    assert group_help.index("\n    list ") < group_help.index("\n    set ")
    assert "\n    show " not in group_help

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "set", "--help"])
    assert exc.value.code == 0
    set_help = capsys.readouterr().out
    # Match on ", --option" rather than "-x, --option" since argparse's
    # short-flag/metavar formatting for options that take a value differs
    # between Python 3.12 (`-v TEXT, --value TEXT`) and 3.13+ (`-v, --value
    # TEXT`); the comma before the long option is stable across versions.
    assert set_help.index(", --json") < set_help.index(", --value ")
    assert set_help.index(", --value ") < set_help.index(", --value-file")


@pytest.mark.parametrize(
    ("option", "destination"),
    (
        ("-v", "value"),
        ("--value", "value"),
        ("-f", "value_file"),
        ("--value-file", "value_file"),
    ),
)
def test_parser_registers_var_set_value_sources(
    option: str,
    destination: str,
) -> None:
    parser = create_parser()

    args = parser.parse_args(["var", "set", "summary", option, "source"])

    assert args.assignments == ["summary"]
    assert getattr(args, destination) == "source"


def test_parser_rejects_both_var_set_value_sources() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(
            [
                "var",
                "set",
                "summary",
                "--value",
                "text",
                "--value-file",
                "value.txt",
            ]
        )

    assert exc.value.code == 2


def test_parser_value_source_requires_a_positional_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "set", "--value", "text"])

    assert exc.value.code == 2
    assert "requires exactly one bare KEY" in capsys.readouterr().err
