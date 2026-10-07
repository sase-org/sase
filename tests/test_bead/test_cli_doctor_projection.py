"""Bead doctor projection repair.

Split from ``tests.test_bead.test_cli_doctor``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from sase.bead import cli_admin, cli_admin_repairs
from sase.bead.model import IssueType
from sase.bead.project import BeadProject


def test_fix_projection_repairs_expected_drift_and_second_run_is_noop(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("One", IssueType.PLAN)
        project.close([issue.id], reason="shipped")
        # Projection-off: materialize the closed state before the helper
        # derives the stale projection from the issues.jsonl content.
        project._export()
    first_close, second_close = _append_redundant_close_and_stale_projection(
        project_dir,
        issue.id,
    )
    commits: list[str] = []

    def auto_commit(message: str, **_kwargs: object) -> bool:
        commits.append(message)
        return False

    monkeypatch.setattr(cli_admin_repairs, "auto_commit_bead_store", auto_commit)
    args = argparse.Namespace(
        fix_design_refs=False,
        fix_projection=True,
        yes=True,
    )

    cli_admin.handle_bead_doctor(args)

    output = capsys.readouterr().out
    assert "Projection repair preview:" in output
    assert f"{json.dumps(second_close)} -> {json.dumps(first_close)}" in output
    assert "Reprojected 1 bead row from canonical events" in output
    # projection-off (sase-1h8.11): the regenerated file is a git-ignored
    # local export, so the repair commits nothing.
    assert commits == []
    with BeadProject(project_dir) as project:
        report = project.doctor_report()
        repaired = project.show(issue.id)
    assert report["projection_drift"] == []
    assert repaired.closed_at == first_close
    assert repaired.close_reason == "shipped"

    cli_admin.handle_bead_doctor(args)

    assert "No projection drift to repair." in capsys.readouterr().out
    assert commits == []


def test_fix_projection_refuses_row_set_drift(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("One", IssueType.PLAN)
    projection = project_dir / "sdd/beads/issues.jsonl"
    projection.write_text("", encoding="utf-8")
    before = projection.read_bytes()
    monkeypatch.setattr(
        cli_admin_repairs,
        "bead_store_mutation",
        lambda *_args: pytest.fail("unsafe projection repair opened a mutation"),
    )

    cli_admin.handle_bead_doctor(
        argparse.Namespace(
            fix_design_refs=False,
            fix_projection=True,
            yes=True,
        )
    )

    assert projection.read_bytes() == before
    assert (
        f"refusing projection repair: {issue.id} would change the issues.jsonl row set"
    ) in capsys.readouterr().err


@pytest.mark.parametrize(
    ("fields", "current_updates", "reduced_updates", "expected"),
    [
        (
            ["status"],
            {"status": "open"},
            {"status": "closed"},
            "changes unexpected field(s): status",
        ),
        (
            ["title"],
            {"title": "stale"},
            {"title": "canonical"},
            "changes unexpected field(s): title",
        ),
        (
            ["closed_at"],
            {"closed_at": "2026-07-30T12:00:00Z"},
            {"closed_at": "2026-07-30T12:01:00Z"},
            "moves closed_at later",
        ),
    ],
)
def test_projection_repair_guard_refuses_unexpected_shapes(
    fields: list[str],
    current_updates: dict[str, object],
    reduced_updates: dict[str, object],
    expected: str,
) -> None:
    current = {"status": "closed", **current_updates}
    reduced = {"status": "closed", **reduced_updates}

    refusal = cli_admin_repairs._projection_repair_refusal(
        [
            {
                "issue_id": "beads-1",
                "changed_fields": fields,
                "current": current,
                "reduced": reduced,
            }
        ]
    )

    assert refusal is not None
    assert expected in refusal


def _append_redundant_close_and_stale_projection(
    project_dir: Path,
    issue_id: str,
) -> tuple[str, str]:
    projection_path = project_dir / "sdd/beads/issues.jsonl"
    current = json.loads(projection_path.read_text(encoding="utf-8"))
    first_close = str(current["closed_at"])
    second_close = (datetime.now(UTC) + timedelta(minutes=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    stream_path = project_dir / f"sdd/beads/events/streams/{issue_id}.jsonl"
    events = [
        json.loads(line)
        for line in stream_path.read_text(encoding="utf-8").splitlines()
    ]
    duplicate = dict(events[-1])
    duplicate["event_id"] = f"{duplicate['event_id']}:duplicate"
    duplicate["timestamp"] = second_close
    duplicate["payload"] = dict(duplicate["payload"])
    duplicate["payload"]["close_reason"] = None
    with stream_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(duplicate, separators=(",", ":")) + "\n")
    current["closed_at"] = second_close
    current["close_reason"] = None
    current["updated_at"] = second_close
    projection_path.write_text(
        json.dumps(current, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return first_close, second_close
