"""CLI coverage for compact bead show output."""

from __future__ import annotations

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Issue
from sase.main.parser import create_parser
from tests.test_bead.cli_show_test_helpers import show_with_format


def test_show_compact_matches_the_same_list_row(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]

    show_out = show_with_format(phase, "compact", capsys)
    bead_cli.handle_bead_list(create_parser().parse_args(["bead", "list"]))
    list_out = capsys.readouterr().out

    assert show_out.rstrip("\n") in list_out.splitlines()


def test_show_compact_renders_the_type_column(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]
    root = nested_store["root"]

    assert show_with_format(phase, "compact", capsys).startswith("↳ ")
    assert show_with_format(root, "compact", capsys).startswith("▸ ")


def test_show_parser_accepts_color_choices() -> None:
    args = create_parser().parse_args(["bead", "show", "sase-64", "--color", "never"])

    assert args.color == "never"


def test_show_compact_color_modes_override_non_tty(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]

    args = create_parser().parse_args(
        ["bead", "show", phase.id, "--format", "compact", "--color", "never"]
    )
    bead_cli.handle_bead_show(args)
    assert "\x1b[" not in capsys.readouterr().out

    args = create_parser().parse_args(
        ["bead", "show", phase.id, "--format", "compact", "--color", "always"]
    )
    bead_cli.handle_bead_show(args)
    assert "\x1b[" in capsys.readouterr().out
