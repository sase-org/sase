"""End-to-end close-history persistence through ``BeadProject``.

The archiving itself happens in sase-core's reducer, so this test checks the
Python storage layer against real reducer output rather than against
hand-built fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.bead import db as bead_db
from sase.bead.jsonl import import_from_jsonl
from sase.bead.model import IssueType, PhaseSize, ReopenCause, Resolution, Status
from sase.bead.project import BeadProject

_CLOSE_REASON = "Not reproducible on main; the retry shim already covers it."


def test_a_plus_one_reopen_archives_the_close_reason(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path) as project:
        task = project.create(
            "Flaky retry test",
            IssueType.TASK,
            size=PhaseSize.SMALL,
            created_by="axe.scout",
        )
        project.close(
            [task.id],
            reason=_CLOSE_REASON,
            resolution=Resolution.CANCELED,
        )
        issue, changed = project.plus_one(
            task.id.rsplit("-", 1)[-1],
            "Saw the same flake in CI run 4821.",
            reporter="claude.probe",
        )

        assert changed
        assert issue.status == Status.READY

        # The current close is gone; the past close is not.
        assert issue.closed_at is None
        assert issue.close_reason is None
        assert issue.resolution is None

        record = issue.close_history[0]
        assert len(issue.close_history) == 1
        assert record.close_reason == _CLOSE_REASON
        assert record.resolution is Resolution.CANCELED
        assert record.reopened_via is ReopenCause.PLUS_ONE
        assert record.reopened_by == "claude.probe"

        # The join key every presentation surface relies on.
        evidence = issue.plus_one_evidence[0]
        assert record.reopened_at == evidence.timestamp
        assert record.reopened_by == evidence.reporter

        projection = json.loads(
            (project.beads_dir / "issues.jsonl").read_text(encoding="utf-8")
        )
        assert projection["close_history"][0]["close_reason"] == _CLOSE_REASON

        mirror = bead_db.init_db(tmp_path / "compatibility-mirror.db")
        try:
            import_from_jsonl(project.beads_dir / "issues.jsonl", mirror)
            mirrored = bead_db.get_issue(mirror, task.id)
            assert mirrored is not None
            assert mirrored.close_history == issue.close_history
        finally:
            mirror.close()

    with BeadProject(tmp_path) as reopened:
        assert reopened.show(task.id).close_history == issue.close_history
