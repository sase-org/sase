"""Created-window and status filter coverage for ``sase bead list``."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead import cli_query
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject

from tests.main.parser_cli_helpers import parse_sase_args


def test_handle_bead_list_since_keeps_current_beads(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        issue = proj.create("Recent Epic", IssueType.PLAN)

    args = parse_sase_args(["bead", "list", "-f", "json", "--since", "1d"])
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

    args = parse_sase_args(["bead", "list", "-f", "json", "--until", "1d"])
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

    bead_cli.handle_bead_list(parse_sase_args(["bead", "list", "-f", "json"]))
    default_payload = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in default_payload["results"]] == [open_issue.id]

    args = parse_sase_args(["bead", "list", "-f", "json", "--status", "all"])
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

    args = parse_sase_args(["bead", "list", "-f", "json", "--since", "1d"])
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
        first = proj.create("First Task", IssueType.TASK, task_type="bug", size="small")
        second = proj.create(
            "Second Task", IssueType.TASK, task_type="bug", size="small"
        )
        proj.close([first.id], reason="done")
        proj.close([second.id], reason="done")

    args = parse_sase_args(["bead", "list", "-f", "json", "--status", "closed"])
    bead_cli.handle_bead_list(args)
    limited_payload = json.loads(capsys.readouterr().out)

    args = parse_sase_args(
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
    args = parse_sase_args(["bead", "list", "--since", "1w", "--until", "2w"])

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_list(args)

    assert excinfo.value.code == 2
    assert "--since must not be later than --until" in capsys.readouterr().err
