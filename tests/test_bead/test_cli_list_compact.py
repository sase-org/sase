"""Compact-row rendering coverage for ``sase bead list``."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pytest
from rich.cells import cell_len

from sase.ansi_style import xterm256_foreground_style
from sase.bead import cli as bead_cli
from sase.bead import cli_query
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.bead_time_presentation import BEAD_CREATED_GLYPH, BEAD_TIME_CLI_STYLE
from sase.bead_type_presentation import BEAD_TYPE_VALUES, bead_type_presentation
from sase.phase_size_presentation import (
    PHASE_SIZE_ACCENTS,
    PHASE_SIZE_VALUES,
    phase_size_cli_token,
)

from tests.main.parser_cli_helpers import parse_sase_args

_STATUS_GLYPHS = "○◎◇◐✓"
_TYPE_GLYPHS = "▸↳◆⚑"


def _seed_one_of_each_type(project_dir: Path) -> dict[str, str]:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Plan Bead", IssueType.PLAN)
        task = proj.create("Task Bead", IssueType.TASK, task_type="bug", size="small")
        phase = proj.create("Phase Bead", IssueType.PHASE, parent_id=plan.id)
    return {"plan": plan.id, "phase": phase.id, "task": task.id}


def _compact_row_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line and line[0] in _TYPE_GLYPHS]


def test_handle_bead_list_compact_summary_counts_printed_limited_rows(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Plan Bead", IssueType.PLAN)
        phase = proj.create("Phase Bead", IssueType.PHASE, parent_id=plan.id)
        task = proj.create("Task Bead", IssueType.TASK, task_type="bug", size="small")

    args = parse_sase_args(["bead", "list", "--limit", "2", "--color", "never"])
    bead_cli.handle_bead_list(args)

    output = capsys.readouterr().out
    assert output.endswith("\n\n2 open beads · ↳ 1  ◆ 1 · 1 hidden\n")
    row_lines = _compact_row_lines(output)
    assert len(row_lines) == 2
    assert phase.id in row_lines[0]
    assert task.id in row_lines[1]


def test_handle_bead_list_implicit_closed_summary_hint_respects_explicit_limit(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_query, "DEFAULT_CLOSED_LIST_LIMIT", 1)
    with BeadProject(project_dir) as proj:
        first = proj.create("First Closed", IssueType.PLAN)
        second = proj.create("Second Closed", IssueType.PLAN)
        proj.close([first.id], reason="done")
        proj.close([second.id], reason="done")

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "--color", "never"]))
    implicit = capsys.readouterr().out
    assert implicit.endswith("\n\n1 closed plan · 1 hidden (--limit 0 shows all)\n")

    bead_cli.handle_bead_list(
        parse_sase_args(["bead", "list", "--limit", "1", "--color", "never"])
    )
    explicit = capsys.readouterr().out
    assert explicit.endswith("\n\n1 closed plan · 1 hidden\n")
    assert "--limit 0 shows all" not in explicit


def test_list_compact_renders_type_glyph_only_per_type(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ids = _seed_one_of_each_type(project_dir)

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list"]))
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


def test_list_compact_type_cells_share_equal_cell_width(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_one_of_each_type(project_dir)

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list"]))
    lines = _compact_row_lines(capsys.readouterr().out)

    # Everything up to the status glyph is the type column plus separator; its
    # rendered cell width matches across rows locks in Decision 4's alignment
    # guarantee even if the glyph vocabulary changes width later.
    widths = {
        cell_len(line[: next(i for i, ch in enumerate(line) if ch in _STATUS_GLYPHS)])
        for line in lines
    }
    assert len(widths) == 1


def test_list_compact_renders_size_tokens_for_every_stored_size(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        ids = {
            value: proj.create(
                f"{value.title()} Task", IssueType.TASK, task_type="bug", size=value
            ).id
            for value in PHASE_SIZE_VALUES
        }

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "--color", "never"]))
    lines = _compact_row_lines(capsys.readouterr().out)

    for value, issue_id in ids.items():
        line = next(line for line in lines if issue_id in line)
        assert f"○ {phase_size_cli_token(value, use_color=False)} {issue_id} ·" in line

    prefixes = {
        cell_len(line[: line.index(issue_id)])
        for value, issue_id in ids.items()
        for line in lines
        if issue_id in line
    }
    assert len(prefixes) == 1


def test_list_compact_collapses_size_column_when_no_rows_are_sized(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Plan Only", IssueType.PLAN)

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "--color", "never"]))

    assert (
        capsys.readouterr().out
        == f"▸   ○ {issue.id} · Plan Only  ⧖ now\n\n1 open plan\n"
    )


def test_list_compact_pads_unsized_rows_when_any_row_is_sized(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Plan Bead", IssueType.PLAN)
        task = proj.create("Large Task", IssueType.TASK, task_type="bug", size="large")

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "--color", "never"]))
    lines = _compact_row_lines(capsys.readouterr().out)
    plan_line = next(line for line in lines if plan.id in line)
    task_line = next(line for line in lines if task.id in line)

    assert f"○    {plan.id} ·" in plan_line
    assert f"○  L {task.id} ·" in task_line
    assert cell_len(plan_line[: plan_line.index(plan.id)]) == cell_len(
        task_line[: task_line.index(task.id)]
    )


def test_list_formats_render_sizes_coherently(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Parent", IssueType.PLAN)
        unsized = proj.create("Unsized Phase", IssueType.PHASE, parent_id=plan.id)
        sized = proj.create(
            "Sized Task", IssueType.TASK, task_type="bug", size="xlarge"
        )

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "--color", "never"]))
    compact = capsys.readouterr().out
    sized_line = next(line for line in compact.splitlines() if sized.id in line)
    unsized_line = next(line for line in compact.splitlines() if unsized.id in line)
    assert f"○ XL {sized.id} ·" in sized_line
    assert f"○    {unsized.id} ·" in unsized_line

    bead_cli.handle_bead_show(parse_sase_args(["bead", "show", sized.id]))
    assert "Size: xlarge" in capsys.readouterr().out
    bead_cli.handle_bead_show(parse_sase_args(["bead", "show", unsized.id]))
    assert "Size: small (default)" in capsys.readouterr().out

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "-f", "json"]))
    rows = {
        row["id"]: row["size"] for row in json.loads(capsys.readouterr().out)["results"]
    }
    assert rows[sized.id] == "xlarge"
    assert rows[unsized.id] is None


def test_list_compact_color_modes_override_non_tty(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_one_of_each_type(project_dir)
    with BeadProject(project_dir) as proj:
        proj.create(
            "Flag Bead",
            IssueType.TASK,
            size="small",
            task_type="flag",
            task_type_fields={
                "key": "demo_key",
                "kind": "beta",
                "when_enabled": "on",
                "when_disabled": "off",
                "remove_when": "done",
                "remove_by_date": "2026-12-01",
                "remove_by_release": "0.19.0",
            },
        )

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "--color", "never"]))
    assert "\x1b[" not in capsys.readouterr().out

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "--color", "always"]))
    colored = capsys.readouterr().out
    assert "\x1b[" in colored
    for value in BEAD_TYPE_VALUES:
        presentation = bead_type_presentation(value)
        assert presentation.cli_style in colored
    assert xterm256_foreground_style(PHASE_SIZE_ACCENTS["small"]) in colored


def test_list_compact_renders_flag_key_and_due_cells(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.__version__", "0.19.0")
    monkeypatch.setattr(
        "sase.bead_summary_presentation.core_time.local_now",
        lambda: datetime(2026, 12, 7, 12, 0, 0),
    )
    monkeypatch.setattr(
        "sase.bead.cli_query_render.core_time.local_now",
        lambda: datetime(2026, 12, 7, 12, 0, 0),
    )
    with BeadProject(project_dir) as proj:
        issue = proj.create(
            "Flag Bead",
            IssueType.TASK,
            size="small",
            task_type="flag",
            task_type_fields={
                "key": "demo_key",
                "kind": "beta",
                "when_enabled": "on",
                "when_disabled": "off",
                "remove_when": "done",
                "remove_by_date": "2026-12-01",
                "remove_by_release": "0.19.0",
            },
        )

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "--color", "never"]))
    output = capsys.readouterr().out
    line = next(line for line in _compact_row_lines(output) if issue.id in line)

    assert "· Flag Bead  ⚑ demo_key DUE ⧗ +6d" in line
    assert output.endswith("\n\n1 open task · ⧗ 1 due flag\n")


def test_list_compact_renders_typed_flag_task_cells(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.__version__", "0.19.0")
    monkeypatch.setattr(
        "sase.bead_summary_presentation.core_time.local_now",
        lambda: datetime(2026, 12, 7, 12, 0, 0),
    )
    monkeypatch.setattr(
        "sase.bead.cli_query_render.core_time.local_now",
        lambda: datetime(2026, 12, 7, 12, 0, 0),
    )
    with BeadProject(project_dir) as proj:
        issue = proj.create(
            "Flag Bead",
            IssueType.TASK,
            size="small",
            task_type="flag",
            task_type_fields={
                "key": "demo_key",
                "kind": "beta",
                "when_enabled": "new path",
                "when_disabled": "old path",
                "remove_when": "when proven",
                "remove_by_date": "2026-12-01",
                "remove_by_release": "0.19.0",
            },
        )

    bead_cli.handle_bead_list(
        parse_sase_args(["bead", "list", "-T", "flag", "--color", "never"])
    )
    output = capsys.readouterr().out
    line = next(line for line in _compact_row_lines(output) if issue.id in line)

    assert "⚑" in line
    assert "· Flag Bead  ⚑ demo_key DUE ⧗ +6d" in line
    assert output.endswith("\n\n1 open task · ⧗ 1 due flag\n")


def test_list_compact_no_color_env_suppresses_escapes(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_one_of_each_type(project_dir)
    monkeypatch.setenv("NO_COLOR", "1")

    # NO_COLOR only governs the "auto" mode; leaving --color unset exercises it.
    bead_cli.handle_bead_list(parse_sase_args(["bead", "list"]))

    assert "\x1b[" not in capsys.readouterr().out


def test_list_compact_default_auto_is_colorless_under_pytest_capture(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_one_of_each_type(project_dir)

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list"]))

    assert "\x1b[" not in capsys.readouterr().out


def test_list_compact_preserves_parent_suffix_and_separator(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ids = _seed_one_of_each_type(project_dir)

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list"]))
    lines = _compact_row_lines(capsys.readouterr().out)

    phase_line = next(line for line in lines if ids["phase"] in line)
    assert f"· Phase Bead ← {ids['plan']}" in phase_line

    plan_line = next(line for line in lines if ids["plan"] in line and "·" in line)
    # A parentless bead ends at its title, followed only by the trailing
    # created cell.
    assert plan_line.endswith("· Plan Bead  ⧖ now")


def test_list_compact_created_cell_carries_the_shared_glyph_and_accent(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_one_of_each_type(project_dir)

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "--color", "always"]))
    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if BEAD_CREATED_GLYPH in line
    ]

    assert lines
    for line in lines:
        assert line.endswith(f"  {BEAD_TIME_CLI_STYLE}{BEAD_CREATED_GLYPH} now\x1b[0m")
