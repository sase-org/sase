"""CLI coverage for ``sase bead epic-symbols``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.main import bead_fast_path
from sase.main.bead_fast_path import try_handle_bead_fast_path
from sase.main.parser import create_parser


def test_epic_symbols_parser_accepts_optional_id_and_format() -> None:
    parser = create_parser()

    bare = parser.parse_args(["bead", "epic-symbols"])
    scoped = parser.parse_args(
        ["bead", "epic-symbols", "sase-64", "--format", "json", "--color", "never"]
    )

    assert bare.bead_subcommand == "epic-symbols"
    assert bare.id is None
    assert bare.format == "compact"
    assert scoped.id == "sase-64"
    assert scoped.format == "json"
    assert scoped.color == "never"


def test_fast_path_defers_epic_symbols_to_argparse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_context(argv: list[str]) -> None:
        raise AssertionError(f"context should not resolve for epic-symbols: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert try_handle_bead_fast_path(["epic-symbols"]) is None
    assert try_handle_bead_fast_path(["epic-symbols", "sase-64"]) is None


def test_epic_symbols_lists_only_the_requested_bead_tree(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Ranking", IssueType.PLAN, tier=BeadTier.EPIC)
        phase = project.create("Scoring", IssueType.PHASE, parent_id=epic.id)
    project_dir.joinpath("Justfile").write_text(
        "\n".join(
            [
                f'--epic-symbol "{epic.id}(CommonIndex)"',
                f'--epic-symbol "{phase.id}(RankedPlaceholder)"',
                '--epic-symbol "sase-other(IgnoreMe)"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    bead_cli.handle_bead_epic_symbols(
        create_parser().parse_args(
            ["bead", "epic-symbols", epic.id, "--color", "never"]
        )
    )

    output = capsys.readouterr().out
    assert f'--epic-symbol "{epic.id}(CommonIndex)"' in output
    assert f'--epic-symbol "{phase.id}(RankedPlaceholder)"' in output
    assert "sase-other" not in output
    assert "Justfile:" in output


def test_epic_symbols_json_includes_empty_result_for_unrelated_bead(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Other work", IssueType.PLAN)
    project_dir.joinpath("Justfile").write_text(
        '--epic-symbol "sase-other(IgnoreMe)"\n',
        encoding="utf-8",
    )

    bead_cli.handle_bead_epic_symbols(
        create_parser().parse_args(
            ["bead", "epic-symbols", issue.id, "--format", "json"]
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["bead_id"] == issue.id
    assert payload["entries"] == []
    assert payload["justfile"] is not None


def test_epic_symbols_reports_empty_working_tree(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bead_cli.handle_bead_epic_symbols(
        create_parser().parse_args(["bead", "epic-symbols"])
    )

    assert capsys.readouterr().out == "No --epic-symbol entries in this working tree.\n"
