"""CLI coverage for ``sase bead list``."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest
from rich.cells import cell_len

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.bead_type_presentation import BEAD_TYPE_VALUES, bead_type_presentation
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
    assert args.color == "auto"
    assert args.format == "compact"
    assert args.limit == 2
    assert args.status == ["open", "closed"]
    assert args.tier == ["epic"]
    assert args.type == ["phase"]


def test_list_parser_accepts_color_choices() -> None:
    args = create_parser().parse_args(["bead", "list", "--color", "never"])

    assert args.color == "never"


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


def _seed_one_of_each_type(project_dir: Path) -> dict[str, str]:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Plan Bead", IssueType.PLAN)
        task = proj.create("Task Bead", IssueType.TASK)
        phase = proj.create("Phase Bead", IssueType.PHASE, parent_id=plan.id)
    return {"plan": plan.id, "phase": phase.id, "task": task.id}


def test_list_compact_renders_type_glyph_only_per_type(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ids = _seed_one_of_each_type(project_dir)

    bead_cli.handle_bead_list(create_parser().parse_args(["bead", "list"]))
    lines = capsys.readouterr().out.splitlines()

    expected = {
        "plan": "▸",
        "phase": "↳",
        "task": "◆",
    }
    for bead_type, glyph in expected.items():
        line = next(line for line in lines if ids[bead_type] in line)
        assert line.startswith(f"{glyph} ")
        prefix = line[: next(i for i, ch in enumerate(line) if ch in _STATUS_GLYPHS)]
        assert bead_type not in prefix


_STATUS_GLYPHS = "○◎◇◐✓"


def test_list_compact_type_cells_share_equal_cell_width(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_one_of_each_type(project_dir)

    bead_cli.handle_bead_list(create_parser().parse_args(["bead", "list"]))
    lines = capsys.readouterr().out.splitlines()

    # Everything up to the status glyph is the type column plus separator; its
    # rendered cell width matches across rows locks in Decision 4's alignment
    # guarantee even if the glyph vocabulary changes width later.
    widths = {
        cell_len(line[: next(i for i, ch in enumerate(line) if ch in _STATUS_GLYPHS)])
        for line in lines
    }
    assert len(widths) == 1


def test_list_compact_color_modes_override_non_tty(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_one_of_each_type(project_dir)

    bead_cli.handle_bead_list(
        create_parser().parse_args(["bead", "list", "--color", "never"])
    )
    assert "\x1b[" not in capsys.readouterr().out

    bead_cli.handle_bead_list(
        create_parser().parse_args(["bead", "list", "--color", "always"])
    )
    colored = capsys.readouterr().out
    assert "\x1b[" in colored
    for value in BEAD_TYPE_VALUES:
        presentation = bead_type_presentation(value)
        assert presentation.cli_style in colored


def test_list_compact_no_color_env_suppresses_escapes(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_one_of_each_type(project_dir)
    monkeypatch.setenv("NO_COLOR", "1")

    # NO_COLOR only governs the "auto" mode; leaving --color unset exercises it.
    bead_cli.handle_bead_list(create_parser().parse_args(["bead", "list"]))

    assert "\x1b[" not in capsys.readouterr().out


def test_list_compact_default_auto_is_colorless_under_pytest_capture(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_one_of_each_type(project_dir)

    bead_cli.handle_bead_list(create_parser().parse_args(["bead", "list"]))

    assert "\x1b[" not in capsys.readouterr().out


def test_list_compact_preserves_parent_suffix_and_separator(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ids = _seed_one_of_each_type(project_dir)

    bead_cli.handle_bead_list(create_parser().parse_args(["bead", "list"]))
    lines = capsys.readouterr().out.splitlines()

    phase_line = next(line for line in lines if ids["phase"] in line)
    assert f"· Phase Bead ← {ids['plan']}" in phase_line

    plan_line = next(line for line in lines if ids["plan"] in line and "·" in line)
    assert plan_line.endswith("· Plan Bead")
