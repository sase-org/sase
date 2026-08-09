"""CLI coverage for ``sase bead list``."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest
from rich.cells import cell_len

from sase.bead import cli as bead_cli
from sase.bead import cli_query
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.bead_time_presentation import BEAD_CREATED_GLYPH, BEAD_TIME_CLI_STYLE
from sase.bead_type_presentation import BEAD_TYPE_VALUES, bead_type_presentation
from sase.main.parser import create_parser


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


def test_list_parser_accepts_created_date_filters_and_status_all() -> None:
    args = create_parser().parse_args(
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
    short_args = create_parser().parse_args(["bead", "list", "-S", "1w", "-u", "today"])

    assert args.since == "1w"
    assert args.until == "today"
    assert args.status == ["all"]
    assert short_args.since == "1w"
    assert short_args.until == "today"


def test_list_parser_rejects_malformed_created_date(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "list", "--since", "lastweek"])

    assert excinfo.value.code == 2
    assert "Invalid DATE 'lastweek'" in capsys.readouterr().err


def test_list_parser_rejects_negative_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "list", "--limit", "-1"])

    assert excinfo.value.code == 2
    assert "must be a non-negative integer" in capsys.readouterr().err


def test_handle_bead_list_since_keeps_current_beads(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Recent Epic", IssueType.PLAN)

    args = create_parser().parse_args(["bead", "list", "-f", "json", "--since", "1d"])
    bead_cli.handle_bead_list(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["results"][0]["id"] == issue.id


def test_handle_bead_list_until_excludes_current_beads(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create("Recent Epic", IssueType.PLAN)

    args = create_parser().parse_args(["bead", "list", "-f", "json", "--until", "1d"])
    bead_cli.handle_bead_list(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 0
    assert payload["total"] == 0


def test_handle_bead_list_status_all_includes_closed_beads(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        open_issue = proj.create("Open Epic", IssueType.PLAN)
        closed_issue = proj.create("Closed Epic", IssueType.PLAN)
        proj.close([closed_issue.id], reason="done")

    bead_cli.handle_bead_list(
        create_parser().parse_args(["bead", "list", "-f", "json"])
    )
    default_payload = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in default_payload["results"]] == [open_issue.id]

    args = create_parser().parse_args(["bead", "list", "-f", "json", "--status", "all"])
    bead_cli.handle_bead_list(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["statuses"] == [status.value for status in Status]
    assert {row["id"] for row in payload["results"]} == {
        open_issue.id,
        closed_issue.id,
    }


def test_handle_bead_list_json_total_counts_only_created_window(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.bead.project._now", lambda: "2000-01-01T00:00:00Z")
    with BeadProject(project_dir) as proj:
        proj.create("Old Epic", IssueType.PLAN)
    monkeypatch.setattr(
        "sase.bead.project._now",
        lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    with BeadProject(project_dir) as proj:
        issue = proj.create("Recent Epic", IssueType.PLAN)

    args = create_parser().parse_args(["bead", "list", "-f", "json", "--since", "1d"])
    bead_cli.handle_bead_list(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["total"] == 1
    assert payload["results"][0]["id"] == issue.id


def test_handle_bead_list_created_bound_lifts_newest_closed_default(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_query, "DEFAULT_CLOSED_LIST_LIMIT", 1)
    with BeadProject(project_dir) as proj:
        first = proj.create("First Task", IssueType.TASK, size="small")
        second = proj.create("Second Task", IssueType.TASK, size="small")
        proj.close([first.id], reason="done")
        proj.close([second.id], reason="done")

    args = create_parser().parse_args(
        ["bead", "list", "-f", "json", "--status", "closed"]
    )
    bead_cli.handle_bead_list(args)
    limited_payload = json.loads(capsys.readouterr().out)

    args = create_parser().parse_args(
        ["bead", "list", "-f", "json", "--status", "closed", "--since", "1d"]
    )
    bead_cli.handle_bead_list(args)
    bounded_payload = json.loads(capsys.readouterr().out)

    assert limited_payload["count"] == 1
    assert limited_payload["total"] == 2
    assert bounded_payload["count"] == 2
    assert bounded_payload["total"] == 2


def test_handle_bead_list_rejects_since_later_than_until(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        ["bead", "list", "--since", "1w", "--until", "2w"]
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_list(args)

    assert excinfo.value.code == 2
    assert "--since must not be later than --until" in capsys.readouterr().err


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
    assert payload["statuses"] == ["open", "claimed", "ready", "snoozed", "in_progress"]
    assert payload["implied_status_closed"] is False
    assert payload["results"][0]["id"] == issue.id
    assert payload["results"][0]["resolution"] is None


def test_handle_bead_list_includes_snoozed_by_default(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        task = proj.create("Deferrable", IssueType.TASK, size="small")
        proj.update(task.id, status=Status.READY.value)
        proj.snooze(task.id, until="2099-01-01T00:00:00Z", actor="tester@example.com")

    args = create_parser().parse_args(["bead", "list", "-f", "json"])
    bead_cli.handle_bead_list(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["statuses"] == ["open", "claimed", "ready", "snoozed", "in_progress"]
    assert payload["results"][0]["id"] == task.id
    assert payload["results"][0]["status"] == "snoozed"


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
        task = proj.create("Task Bead", IssueType.TASK, size="small")
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
    # A parentless bead ends at its title, followed only by the trailing
    # created cell.
    assert plan_line.endswith("· Plan Bead  ⧖ now")


def test_list_compact_created_cell_carries_the_shared_glyph_and_accent(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_one_of_each_type(project_dir)

    bead_cli.handle_bead_list(
        create_parser().parse_args(["bead", "list", "--color", "always"])
    )
    lines = capsys.readouterr().out.splitlines()

    assert lines
    for line in lines:
        assert line.endswith(f"  {BEAD_TIME_CLI_STYLE}{BEAD_CREATED_GLYPH} now\x1b[0m")
