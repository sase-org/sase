"""Durable planner-completion handoff tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.axe.run_agent_runner_finalize import send_completion_notification
from sase.bead.epic_launch import finish_epic_launch
from sase.bead.epic_launch_handoff import (
    CompletionNotificationPayload,
    claim_epic_completion,
    defer_epic_completion,
    flush_orphaned_deferrals,
)
from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.core.paths import sase_projects_dir, sase_subdir


def _artifacts(
    *,
    project: str = "demo",
    workflow: str = "ace-run",
    timestamp: str = "20260727123456",
) -> Path:
    workflow_dir = sase_projects_dir() / project / "artifacts" / workflow
    path = (
        workflow_dir / timestamp[:6] / timestamp[6:8] / timestamp
        if workflow == "ace-run"
        else workflow_dir / timestamp
    )
    path.mkdir(parents=True)
    return path


def _payload() -> CompletionNotificationPayload:
    return CompletionNotificationPayload(
        sender="user-agent",
        cl_name="demo-cl",
        success=True,
        notes=["claude/opus @planner completed: tale"],
        action="JumpToAgent",
        action_data={
            "cl_name": "demo-cl",
            "raw_suffix": "20260727123456",
            "prompt": "#tale",
        },
        extra_files=["/tmp/report.md"],
        silent=False,
        tags=["done"],
    )


def _runner_kwargs(artifacts_dir: Path) -> dict[str, object]:
    return {
        "cl_name": "demo-cl",
        "artifacts_timestamp": artifacts_dir.name,
        "workflow_name": "tale",
        "success": True,
        "agent_hidden": False,
        "agent_name": "planner",
        "agent_model": "opus",
        "agent_llm_provider": "claude",
        "error_summary": None,
        "error_report_path": None,
        "saved_path": None,
        "diff_path": None,
        "current_artifacts_dir": str(artifacts_dir),
        "markdown_pdf_paths": [],
        "markdown_source_count": None,
        "image_paths": [],
        "video_paths": [],
        "output_path": str(artifacts_dir / "output.log"),
        "step_output": None,
        "prompt": "#tale",
        "outcome": "epic_approved",
    }


def _pending_path(artifacts_dir: Path) -> Path:
    info = parse_agent_artifact_path(artifacts_dir)
    assert info is not None
    key = f"{info.project_name}__{info.timestamp}"
    return sase_subdir("notifications") / "epic_completions" / f"{key}.pending.json"


def _settled_path(artifacts_dir: Path) -> Path:
    return _pending_path(artifacts_dir).with_name(
        _pending_path(artifacts_dir).name.replace(".pending.", ".settled.")
    )


def test_key_matches_host_and_promoted_workflow_paths() -> None:
    host = _artifacts(workflow="ace-run")
    promoted = _artifacts(workflow="workflow-three_phase")

    assert defer_epic_completion(host, _payload())
    host_path = _pending_path(host)
    host_key = json.loads(host_path.read_text(encoding="utf-8"))["key"]
    assert defer_epic_completion(promoted, _payload())
    promoted_path = _pending_path(promoted)
    promoted_key = json.loads(promoted_path.read_text(encoding="utf-8"))["key"]

    assert host_path == promoted_path
    assert host_key == promoted_key
    assert not defer_epic_completion("/tmp/not-an-agent-artifact", _payload())


def test_runner_defers_epic_completion_with_round_trippable_payload() -> None:
    artifacts = _artifacts()
    plan = artifacts / "epic.md"
    plan.write_text("# Epic\n", encoding="utf-8")
    (artifacts / "plan_path.json").write_text(
        json.dumps({"plan_path": str(plan)}),
        encoding="utf-8",
    )

    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        send_completion_notification(**_runner_kwargs(artifacts))

    notify.assert_not_called()
    pending = json.loads(_pending_path(artifacts).read_text(encoding="utf-8"))
    assert pending["plan_file"] == str(plan)
    assert pending["payload"]["sender"] == "user-agent"
    assert pending["payload"]["cl_name"] == "demo-cl"
    assert pending["payload"]["action"] == "JumpToAgent"
    assert pending["payload"]["action_data"]["raw_suffix"] == artifacts.name
    assert pending["payload"]["tags"] == ["done"]


def test_runner_sends_immediately_when_handoff_store_is_unusable(
    tmp_path: Path,
) -> None:
    artifacts = _artifacts()
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    with (
        patch(
            "sase.bead.epic_launch_handoff._epic_completion_store_dir",
            return_value=blocker / "child",
        ),
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        send_completion_notification(**_runner_kwargs(artifacts))

    notify.assert_called_once()
    assert notify.call_args.kwargs["sender"] == "user-agent"


def test_finish_claims_pending_and_sends_one_folded_completion(tmp_path: Path) -> None:
    artifacts = _artifacts()
    assert defer_epic_completion(artifacts, _payload())
    archived = tmp_path / "plans" / "epic.md"
    result = SimpleNamespace(
        dry_run=False,
        epic_id="sase-64",
        archived_plan_path=archived,
        launched=True,
    )

    with (
        patch("sase.bead.epic_launch._update_epic_launch_metadata"),
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        finish_epic_launch(
            str(tmp_path / "epic.md"),
            artifacts_dir=artifacts,
            cl_name="demo-cl",
            result=result,
        )

    notify.assert_called_once()
    kwargs = notify.call_args.kwargs
    assert kwargs["sender"] == "user-agent"
    assert kwargs["cl_name"] == "demo-cl"
    assert kwargs["action"] == "JumpToAgent"
    assert kwargs["action_data"]["raw_suffix"] == artifacts.name
    assert kwargs["notes"][0] == _payload().notes[0]
    assert "Epic sase-64 launched from epic.md" in kwargs["notes"]
    assert f"Plan: {archived}" in kwargs["notes"]
    assert not _pending_path(artifacts).exists()


def test_finish_marks_early_settle_then_runner_sends_without_refolding(
    tmp_path: Path,
) -> None:
    artifacts = _artifacts()
    result = SimpleNamespace(
        dry_run=False,
        epic_id="sase-64",
        archived_plan_path=tmp_path / "plans" / "epic.md",
        launched=True,
    )

    with (
        patch("sase.bead.epic_launch._update_epic_launch_metadata"),
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        finish_epic_launch(
            str(tmp_path / "epic.md"),
            artifacts_dir=artifacts,
            cl_name="demo-cl",
            result=result,
        )
        assert _settled_path(artifacts).exists()
        send_completion_notification(**_runner_kwargs(artifacts))

    assert notify.call_count == 2
    assert notify.call_args_list[0].args[:3] == ("epic-launch", "demo-cl", True)
    completion = notify.call_args_list[1].kwargs
    assert completion["sender"] == "user-agent"
    assert all("Epic sase-64" not in note for note in completion["notes"])
    assert not _settled_path(artifacts).exists()


def test_finish_failure_claims_pending_and_drops_done_tag(tmp_path: Path) -> None:
    artifacts = _artifacts()
    assert defer_epic_completion(artifacts, _payload())

    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        finish_epic_launch(
            str(tmp_path / "epic plan.md"),
            artifacts_dir=artifacts,
            cl_name="demo-cl",
            error=RuntimeError("launch failed"),
        )

    notify.assert_called_once()
    kwargs = notify.call_args.kwargs
    assert kwargs["sender"] == "user-agent"
    assert kwargs["action"] == "JumpToAgent"
    assert kwargs["tags"] is None
    assert "Epic launch failed: launch failed" in kwargs["notes"]
    assert any("Resume with:" in note and "--yes " in note for note in kwargs["notes"])


def test_sweep_preserves_active_then_flushes_orphan_once() -> None:
    artifacts = _artifacts()
    plan = artifacts / "epic.md"
    (artifacts / "plan_path.json").write_text(
        json.dumps({"plan_path": str(plan)}),
        encoding="utf-8",
    )
    assert defer_epic_completion(artifacts, _payload())
    pending_path = _pending_path(artifacts)
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    created = datetime.now(UTC) - timedelta(minutes=5)
    pending["created_at"] = created.isoformat()
    pending_path.write_text(json.dumps(pending), encoding="utf-8")
    active_task = SimpleNamespace(
        tags=["epic", "launch"],
        command=[
            "sase",
            "bead",
            "work",
            str(plan),
            "--artifacts-dir",
            str(artifacts),
        ],
    )

    with (
        patch("sase.tasks.read_tasks", return_value=[active_task]),
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        active_result = flush_orphaned_deferrals()
    assert active_result.active == 1
    assert pending_path.exists()
    notify.assert_not_called()

    with (
        patch("sase.tasks.read_tasks", return_value=[]),
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        flushed_result = flush_orphaned_deferrals()
        second_result = flush_orphaned_deferrals()

    assert flushed_result.flushed == 1
    assert second_result.flushed == 0
    notify.assert_called_once()
    kwargs = notify.call_args.kwargs
    assert kwargs["tags"] is None
    assert "Epic launch outcome is unknown." in kwargs["notes"]
    assert any("Resume with:" in note for note in kwargs["notes"])


def test_sweep_leaves_young_pending_and_reaps_stale_settle() -> None:
    young_artifacts = _artifacts(project="young")
    assert defer_epic_completion(young_artifacts, _payload())
    settled_artifacts = _artifacts(project="settled")
    claim_epic_completion(
        settled_artifacts,
        outcome={
            "success": True,
            "epic_id": "sase-64",
            "plan_file": "/tmp/epic.md",
            "detail": "",
            "settled_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        },
    )

    with patch("sase.tasks.read_tasks", return_value=[]):
        result = flush_orphaned_deferrals()

    assert result.young == 1
    assert result.flushed == 0
    assert result.settled_reaped == 1
    assert _pending_path(young_artifacts).exists()
    assert not _settled_path(settled_artifacts).exists()
