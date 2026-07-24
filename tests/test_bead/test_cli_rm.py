"""CLI parser coverage for ``sase bead rm``."""

from __future__ import annotations

import pytest

from sase.main.parser import create_parser


def test_rm_parser_accepts_one_or_more_ids() -> None:
    parser = create_parser()

    assert parser.parse_args(["bead", "rm", "beads-1"]).ids == ["beads-1"]
    assert parser.parse_args(["bead", "rm", "beads-1", "beads-2"]).ids == [
        "beads-1",
        "beads-2",
    ]


def test_rm_parser_requires_an_id() -> None:
    with pytest.raises(SystemExit, match="2"):
        create_parser().parse_args(["bead", "rm"])


def test_rm_help_documents_plural_required_positional(capsys) -> None:
    with pytest.raises(SystemExit, match="0"):
        create_parser().parse_args(["bead", "rm", "--help"])

    help_text = capsys.readouterr().out
    assert "usage: sase bead rm [-h] ids [ids ...]" in help_text
    assert "One or more issue IDs to remove" in help_text
