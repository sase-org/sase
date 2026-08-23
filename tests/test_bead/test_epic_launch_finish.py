"""Metadata backfill and completion-notification coverage for epic launch."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.bead.epic_launch import _update_epic_launch_metadata, finish_epic_launch


def test_update_epic_launch_metadata_backfills_all_host_fields(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    meta_path = artifacts / "agent_meta.json"
    meta_path.write_text('{"name": "planner"}\n', encoding="utf-8")

    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        _update_epic_launch_metadata(
            artifacts,
            epic_id="sase-64",
            sdd_plan_path="/plans/epic.md",
        )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    epic_started_at = meta.pop("epic_started_at")
    assert isinstance(epic_started_at, str)
    datetime.fromisoformat(epic_started_at)
    assert meta == {
        "name": "planner",
        "epic_bead_id": "sase-64",
        "plan_committed": True,
        "sdd_plan_path": "/plans/epic.md",
    }
    update_index.assert_called_once_with(artifacts)


def test_work_command_backfills_from_structured_result_and_notifies(
    tmp_path: Path,
) -> None:
    result = SimpleNamespace(
        dry_run=False,
        epic_id="sase-64",
        archived_plan_path=tmp_path / "plans" / "epic.md",
        launched=True,
    )
    with (
        patch("sase.bead.epic_launch._update_epic_launch_metadata") as update_metadata,
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        finish_epic_launch(
            str(tmp_path / "epic.md"),
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            result=result,
        )

    update_metadata.assert_called_once_with(
        tmp_path / "artifacts",
        epic_id="sase-64",
        sdd_plan_path=str(result.archived_plan_path),
    )
    assert notify.call_args.args[:3] == ("epic-launch", "demo", True)
    assert "Epic sase-64 launched" in notify.call_args.args[3][0]


def test_work_command_failure_notification_has_complete_resume_hint(
    tmp_path: Path,
) -> None:
    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        finish_epic_launch(
            str(tmp_path / "epic plan.md"),
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            error=RuntimeError("launch failed"),
        )

    assert notify.call_args.args[:3] == ("epic-launch", "demo", False)
    notes = notify.call_args.args[3]
    assert "launch failed" in notes[0]
    assert "--yes " in notes[1]
    assert "--yes-to-all" not in notes[1]
    assert "--artifacts-dir" in notes[1]
    assert "--cl-name demo" in notes[1]


def test_work_command_declined_launch_notifies_failure(tmp_path: Path) -> None:
    result = SimpleNamespace(
        dry_run=False,
        epic_id="sase-64",
        archived_plan_path=tmp_path / "plans" / "epic.md",
        launched=False,
    )
    with (
        patch("sase.bead.epic_launch._update_epic_launch_metadata") as update_metadata,
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        finish_epic_launch(
            str(tmp_path / "epic.md"),
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            result=result,
        )

    update_metadata.assert_not_called()
    assert notify.call_args.args[:3] == ("epic-launch", "demo", False)
    notes = notify.call_args.args[3]
    assert "epic launch was declined" in notes[0]
    assert "--yes " in notes[1]
    assert "--yes-to-all" not in notes[1]


def test_work_command_linking_side_effects_are_best_effort(tmp_path: Path) -> None:
    result = SimpleNamespace(
        dry_run=False,
        epic_id="sase-64",
        archived_plan_path=tmp_path / "plans" / "epic.md",
        launched=True,
    )
    with (
        patch(
            "sase.bead.epic_launch._update_epic_launch_metadata",
            side_effect=OSError("read-only"),
        ),
        patch(
            "sase.notifications.senders.notify_workflow_complete",
            side_effect=OSError("store unavailable"),
        ),
    ):
        finish_epic_launch(
            str(tmp_path / "epic.md"),
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            result=result,
        )
