"""JSON envelope and format-selection coverage for ``sase bead list``.

Argument parsing lives in ``test_cli_list_parser``, created-window and status
filters in ``test_cli_list_filters``, and compact-row rendering in
``test_cli_list_compact``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject

from tests.main.parser_cli_helpers import parse_sase_args


def test_handle_bead_list_json_outputs_envelope(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Open Epic", IssueType.PLAN)

    args = parse_sase_args(["bead", "list", "-f", "json"])
    bead_cli.handle_bead_list(args)

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["count"] == 1
    assert payload["total"] == 1
    assert payload["statuses"] == ["open", "claimed", "ready", "snoozed", "in_progress"]
    assert payload["implied_status_closed"] is False
    assert payload["by_type"] == {"plan": 1, "phase": 0, "task": 0, "flag": 0}
    assert payload["due_flags"] == 0
    assert payload["by_status"] == {
        "open": 1,
        "claimed": 0,
        "ready": 0,
        "snoozed": 0,
        "in_progress": 0,
        "closed": 0,
    }
    assert payload["results"][0]["id"] == issue.id
    assert payload["results"][0]["resolution"] is None
    assert payload["results"][0]["size"] is None
    assert "\n1 open plan\n" not in output


def test_handle_bead_list_json_always_emits_size(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Open Epic", IssueType.PLAN)
        task = proj.create("Sized Task", IssueType.TASK, size="medium")

    args = parse_sase_args(["bead", "list", "-f", "json"])
    bead_cli.handle_bead_list(args)

    rows = {
        row["id"]: row["size"] for row in json.loads(capsys.readouterr().out)["results"]
    }
    assert rows == {plan.id: None, task.id: "medium"}


def test_handle_bead_list_includes_snoozed_by_default(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        task = proj.create("Deferrable", IssueType.TASK, size="small")
        proj.update(task.id, status=Status.READY.value)
        proj.snooze(task.id, until="2099-01-01T00:00:00Z", actor="tester@example.com")

    args = parse_sase_args(["bead", "list", "-f", "json"])
    bead_cli.handle_bead_list(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["statuses"] == ["open", "claimed", "ready", "snoozed", "in_progress"]
    assert payload["results"][0]["id"] == task.id
    assert payload["results"][0]["status"] == "snoozed"


def test_handle_bead_list_json_empty_store_is_valid_envelope(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = parse_sase_args(["bead", "list", "--format", "json"])
    bead_cli.handle_bead_list(args)

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["count"] == 0
    assert payload["total"] == 0
    assert payload["implied_status_closed"] is False
    assert payload["by_type"] == {"plan": 0, "phase": 0, "task": 0, "flag": 0}
    assert payload["due_flags"] == 0
    assert payload["by_status"] == {
        "open": 0,
        "claimed": 0,
        "ready": 0,
        "snoozed": 0,
        "in_progress": 0,
        "closed": 0,
    }
    assert payload["results"] == []
    assert "No issues found." not in output


def test_handle_bead_list_json_reports_implicit_closed_without_notice(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Closed Epic", IssueType.PLAN)
        proj.close([issue.id], reason="done")

    args = parse_sase_args(["bead", "list", "-f", "json"])
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

    args = parse_sase_args(["bead", "list", "-f", "json", "--limit", "1"])
    bead_cli.handle_bead_list(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["total"] == 2
    assert payload["by_type"] == {"plan": 1, "phase": 0, "task": 0, "flag": 0}
    assert payload["due_flags"] == 0
    assert payload["by_status"] == {
        "open": 1,
        "claimed": 0,
        "ready": 0,
        "snoozed": 0,
        "in_progress": 0,
        "closed": 0,
    }


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

    args = parse_sase_args(["bead", "list", "-f", "full"])
    bead_cli.handle_bead_list(args)
    list_out = capsys.readouterr().out

    bead_cli.handle_bead_show(parse_sase_args(["bead", "show", issue.id]))
    show_out = capsys.readouterr().out

    assert list_out == f"{show_out}\n1 open plan\n"


def test_handle_bead_list_explicit_compact_matches_default(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        proj.create("Compact Epic", IssueType.PLAN)

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list"]))
    default_out = capsys.readouterr().out

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "--format", "compact"]))
    explicit_out = capsys.readouterr().out

    assert explicit_out == default_out
