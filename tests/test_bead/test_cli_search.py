"""CLI coverage for ``sase bead search``."""

from __future__ import annotations

import json
import re
import sys

import pytest
from rich.cells import cell_len

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.main.entry import main as sase_main
from tests.main.parser_cli_helpers import parse_sase_args

EMPTY_ANSI_SPAN_RE = re.compile(r"\x1b\[[0-9;]*m\x1b\[0m")


def test_search_parser_sets_query_filters_and_output_options() -> None:
    args = parse_sase_args(
        [
            "bead",
            "search",
            "Needle",
            "--color",
            "never",
            "--format",
            "json",
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
    assert args.bead_subcommand == "search"
    assert args.query == "Needle"
    assert args.color == "never"
    assert args.format == "json"
    assert args.limit == 2
    assert args.regex is False
    assert args.status == ["open", "closed"]
    assert args.tier == ["epic"]
    assert args.type == ["phase"]


@pytest.mark.parametrize("flag", ["-e", "--regex"])
def test_search_parser_sets_regex_flag(flag: str) -> None:
    args = parse_sase_args(["bead", "search", "Needle", flag])

    assert args.regex is True


def test_search_parser_rejects_negative_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_sase_args(["bead", "search", "needle", "--limit", "-1"])

    assert excinfo.value.code == 2
    assert "must be a non-negative integer" in capsys.readouterr().err


def test_handle_bead_search_compact_includes_closed_and_match_reason(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create(
            "Needle Epic",
            IssueType.PLAN,
            description="Needle in description",
        )
        proj.create("Notes Carrier", IssueType.PLAN, notes="private needle note")
        closed = proj.create("Closed Needle", IssueType.PLAN)
        proj.close([closed.id], reason="done")

    args = parse_sase_args(["bead", "search", "needle"])
    bead_cli.handle_bead_search(args)

    out = capsys.readouterr().out
    assert "○" in out
    assert "Needle Epic" in out
    assert "Needle in description" in out
    assert 'notes: "private needle note"' in out
    assert "✓" in out
    assert "Closed Needle" in out


def test_handle_bead_search_compact_snippet_uses_matching_line(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create(
            "Multiline Description",
            IssueType.PLAN,
            description="Overview line\nNeedle appears later",
        )

    args = parse_sase_args(["bead", "search", "needle"])
    bead_cli.handle_bead_search(args)

    out = capsys.readouterr().out
    assert "Multiline Description" in out
    assert "Needle appears later" in out
    assert "Overview line" not in out


def test_handle_bead_search_regex_matches_when_literal_cannot(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create("Needle Epic", IssueType.PLAN)

    literal_args = parse_sase_args(["bead", "search", "^Needle"])
    bead_cli.handle_bead_search(literal_args)
    assert capsys.readouterr().out == 'No beads match "^Needle".\n'

    regex_args = parse_sase_args(["bead", "search", "^Needle", "--regex"])
    bead_cli.handle_bead_search(regex_args)
    out = capsys.readouterr().out
    assert "Needle Epic" in out


def test_handle_bead_search_literal_mode_treats_metacharacters_literally(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create("Literal a.c", IssueType.PLAN)
        proj.create("Letters abc", IssueType.PLAN)

    args = parse_sase_args(["bead", "search", "a.c"])
    bead_cli.handle_bead_search(args)

    out = capsys.readouterr().out
    assert "Literal a.c" in out
    assert "Letters abc" not in out


def test_handle_bead_search_regex_compact_snippet_uses_matching_line(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create(
            "Multiline Description",
            IssueType.PLAN,
            description="Overview line\nNeedle-42 appears later",
        )

    args = parse_sase_args(["bead", "search", r"Needle-\d+", "--regex"])
    bead_cli.handle_bead_search(args)

    out = capsys.readouterr().out
    assert "Multiline Description" in out
    assert "Needle-42 appears later" in out
    assert "Overview line" not in out


def test_handle_bead_search_compact_renders_aligned_type_glyphs(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Needle Plan", IssueType.PLAN)
        phase = proj.create(
            "Needle Phase",
            IssueType.PHASE,
            parent_id=plan.id,
        )
        task = proj.create("Needle Task", IssueType.TASK, size="small")

    args = parse_sase_args(["bead", "search", "needle", "--color", "never"])
    bead_cli.handle_bead_search(args)

    lines = capsys.readouterr().out.splitlines()
    expected = {
        plan.id: "▸",
        phase.id: "↳",
        task.id: "◆",
    }
    prefixes: list[str] = []
    for issue_id, glyph in expected.items():
        line = next(line for line in lines if f" {issue_id} ·" in line)
        assert line.startswith(f"{glyph} ")
        status_index = next(i for i, char in enumerate(line) if char in "○◎◇◐✓")
        prefixes.append(line[:status_index])

    assert len({cell_len(prefix) for prefix in prefixes}) == 1


def test_handle_bead_search_compact_colors_type_glyphs(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Needle Plan", IssueType.PLAN)
        proj.create("Needle Phase", IssueType.PHASE, parent_id=plan.id)
        proj.create("Needle Task", IssueType.TASK, size="small")

    args = parse_sase_args(["bead", "search", "needle", "--color", "always"])
    bead_cli.handle_bead_search(args)

    out = capsys.readouterr().out
    assert "\x1b[38;5;220m▸\x1b[0m " in out
    assert "\x1b[38;5;117m↳\x1b[0m " in out
    assert "\x1b[38;5;177m◆\x1b[0m " in out


def test_handle_bead_search_json_outputs_envelope(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Needle Epic", IssueType.PLAN)

    args = parse_sase_args(["bead", "search", "needle", "--format", "json"])
    bead_cli.handle_bead_search(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "needle"
    assert payload["regex"] is False
    assert payload["count"] == 1
    assert payload["results"][0]["issue"]["id"] == issue.id
    assert payload["results"][0]["matched_fields"] == ["title"]


def test_handle_bead_search_json_outputs_regex_mode(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Needle Epic", IssueType.PLAN)

    args = parse_sase_args(["bead", "search", "^needle", "--regex", "--format", "json"])
    bead_cli.handle_bead_search(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "^needle"
    assert payload["regex"] is True
    assert payload["count"] == 1
    assert payload["results"][0]["issue"]["id"] == issue.id


def test_handle_bead_search_full_reuses_show_rendering(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Needle Epic", IssueType.PLAN, description="Full body")

    args = parse_sase_args(["bead", "search", "needle", "--format", "full"])
    bead_cli.handle_bead_search(args)
    search_out = capsys.readouterr().out

    bead_cli.handle_bead_show(parse_sase_args(["bead", "show", issue.id]))
    show_out = capsys.readouterr().out

    assert search_out == show_out


def test_handle_bead_search_no_matches_is_success(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create("Present", IssueType.PLAN)

    args = parse_sase_args(["bead", "search", "missing"])
    bead_cli.handle_bead_search(args)

    assert capsys.readouterr().out == 'No beads match "missing".\n'


def test_handle_bead_search_whitespace_query_exits_usage_error(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = parse_sase_args(["bead", "search", "   "])

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_search(args)

    assert excinfo.value.code == 2
    assert capsys.readouterr().err == "Error: search query cannot be empty\n"


def test_handle_bead_search_invalid_regex_exits_usage_error(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create("Present", IssueType.PLAN)
    args = parse_sase_args(["bead", "search", "[", "--regex"])

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_search(args)

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Error: invalid search regex: ")


@pytest.mark.parametrize("output_format", ["compact", "json", "full"])
def test_bead_search_entrypoint_invalid_regex_agrees_across_formats(
    project_dir,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create("Present", IssueType.PLAN)

    monkeypatch.setattr(
        sys,
        "argv",
        ["sase", "bead", "search", "[", "--regex", "--format", output_format],
    )

    with pytest.raises(SystemExit) as excinfo:
        sase_main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert captured.out == ""
    assert captured.err.startswith("Error: invalid search regex: ")


@pytest.mark.parametrize("output_format", ["compact", "json", "full"])
def test_bead_search_entrypoint_zero_width_regex_matches_without_empty_highlights(
    project_dir,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Needle Epic", IssueType.PLAN)

    argv = [
        "sase",
        "bead",
        "search",
        "^",
        "--regex",
        "--format",
        output_format,
    ]
    if output_format != "json":
        argv.extend(["--color", "always"])
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as excinfo:
        sase_main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 0
    assert captured.err == ""
    if output_format == "json":
        payload = json.loads(captured.out)
        assert payload["regex"] is True
        assert payload["count"] == 1
        assert payload["results"][0]["issue"]["id"] == issue.id
        assert "title" in payload["results"][0]["matched_fields"]
    else:
        assert issue.id in captured.out
        assert "Needle Epic" in captured.out
        assert not EMPTY_ANSI_SPAN_RE.search(captured.out)


def test_handle_bead_search_compact_appends_the_bead_created_cell(
    project_dir,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create("Needle Epic", IssueType.PLAN)

    args = parse_sase_args(["bead", "search", "needle", "--color", "never"])
    bead_cli.handle_bead_search(args)

    row = capsys.readouterr().out.splitlines()[0]
    assert row.endswith("· Needle Epic  ⧖ now")
