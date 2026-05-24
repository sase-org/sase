"""Parser and registry tests for bare ``sase init`` onboarding."""

from __future__ import annotations

import pytest

from sase.main.init_registry import iter_init_command_specs
from sase.main.parser import create_parser


def test_parser_accepts_bare_init_modes() -> None:
    parser = create_parser()

    init_args = parser.parse_args(["init"])
    assert init_args.command == "init"
    assert init_args.init_subcommand is None
    assert init_args.yes is False
    assert init_args.check is False

    yes_args = parser.parse_args(["init", "--yes"])
    assert yes_args.init_subcommand is None
    assert yes_args.yes is True

    check_args = parser.parse_args(["init", "--check"])
    assert check_args.init_subcommand is None
    assert check_args.check is True

    short_check_args = parser.parse_args(["init", "-c"])
    assert short_check_args.init_subcommand is None
    assert short_check_args.check is True


def test_parser_accepts_scoped_init_check_modes() -> None:
    parser = create_parser()

    sdd_short_args = parser.parse_args(["sdd", "init", "-c"])
    assert sdd_short_args.command == "sdd"
    assert sdd_short_args.sdd_subcommand == "init"
    assert sdd_short_args.check is True

    sdd_long_args = parser.parse_args(["sdd", "init", "--check"])
    assert sdd_long_args.check is True

    memory_short_args = parser.parse_args(["memory", "init", "-c"])
    assert memory_short_args.command == "memory"
    assert memory_short_args.memory_subcommand == "init"
    assert memory_short_args.check is True
    assert memory_short_args.no_commit is False

    memory_long_args = parser.parse_args(["memory", "init", "--check"])
    assert memory_long_args.check is True

    init_sdd_args = parser.parse_args(["init", "sdd", "--check"])
    assert init_sdd_args.command == "init"
    assert init_sdd_args.init_subcommand == "sdd"
    assert init_sdd_args.check is True

    init_memory_args = parser.parse_args(["init", "memory", "--check"])
    assert init_memory_args.command == "init"
    assert init_memory_args.init_subcommand == "memory"
    assert init_memory_args.check is True

    parent_sdd_args = parser.parse_args(["init", "--check", "sdd"])
    assert parent_sdd_args.init_subcommand == "sdd"
    assert parent_sdd_args.check is True

    parent_memory_args = parser.parse_args(["init", "--check", "memory"])
    assert parent_memory_args.init_subcommand == "memory"
    assert parent_memory_args.check is True


def test_init_help_lists_existing_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["init", "--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "amd" in out
    assert "memory" in out
    assert "sdd" in out
    assert "skills" in out
    assert "-c, --check" in out
    assert "Advanced deploy controls live on explicit subcommands" in out


def test_registry_order_is_amd_memory_sdd_skills() -> None:
    assert tuple(spec.name for spec in iter_init_command_specs()) == (
        "amd",
        "memory",
        "sdd",
        "skills",
    )
