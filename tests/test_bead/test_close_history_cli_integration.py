"""Real reducer, real search, real history: the chain phase-4's unit test could
not reach because it only exercised ``_search_field_value`` directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, PhaseSize, Resolution
from sase.bead.project import BeadProject
from sase.main.parser import create_parser

_CLOSE_REASON = "superseded by the kaleidoscope rewrite"


def _close_and_reopen_task(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        task = project.create(
            "Rewrite target",
            IssueType.TASK,
            task_type="bug",
            size=PhaseSize.SMALL,
            created_by="axe.scout",
        )
        project.close(
            [task.id],
            reason=_CLOSE_REASON,
            resolution=Resolution.CANCELED,
        )
        project.plus_one(
            task.id.rsplit("-", 1)[-1],
            "Still relevant after the rewrite landed.",
            reporter="claude.probe",
        )
    return task.id


def test_search_finds_an_archived_close_reason_end_to_end(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = _close_and_reopen_task(project_dir)

    args = create_parser().parse_args(
        ["bead", "search", "kaleidoscope", "--format", "json"]
    )
    bead_cli.handle_bead_search(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    result = payload["results"][0]
    assert result["issue"]["id"] == task_id
    assert "close_history" in result["matched_fields"]

    compact_args = create_parser().parse_args(["bead", "search", "kaleidoscope"])
    bead_cli.handle_bead_search(compact_args)
    compact_out = capsys.readouterr().out
    assert task_id in compact_out
    assert "kaleidoscope" in compact_out


def test_history_reports_the_close_history_field_transition(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = _close_and_reopen_task(project_dir)

    args = create_parser().parse_args(
        ["bead", "history", task_id, "-F", "close_history", "--format", "json"]
    )
    bead_cli.handle_bead_history(args)

    payload = json.loads(capsys.readouterr().out)
    changes = [
        change
        for entry in payload["entries"]
        for change in entry["changes"]
        if change["field"] == "close_history"
    ]
    assert len(changes) == 1
    to_value = changes[0]["to"]
    assert to_value[0]["close_reason"] == _CLOSE_REASON

    compact_args = create_parser().parse_args(["bead", "history", task_id])
    bead_cli.handle_bead_history(compact_args)
    assert "close_history" in capsys.readouterr().out
