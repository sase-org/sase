"""Shared approved-epic launch helper tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.bead.epic_launch import (
    _update_epic_launch_metadata,
    build_epic_launch_argv,
    finish_epic_launch,
    resolve_epic_launch_cwd,
    submit_epic_launch_task,
)


def test_build_epic_launch_argv_carries_approval_linking_options() -> None:
    assert build_epic_launch_argv(
        "/tmp/epic plan.md",
        artifacts_dir="/tmp/artifacts",
        cl_name="demo",
    ) == [
        "sase",
        "bead",
        "work",
        "/tmp/epic plan.md",
        "--yes-to-all",
        "--artifacts-dir",
        "/tmp/artifacts",
        "--cl-name",
        "demo",
    ]


def test_resolve_epic_launch_cwd_prefers_canonical_project_file(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "sase_10"
    project_dir.mkdir()
    project_file = (
        tmp_path / "projects" / "gh_sase-org__sase" / "gh_sase-org__sase.sase"
    )
    primary = tmp_path / "primary"
    primary.mkdir()

    with (
        patch("sase.workspace_provider.get_workspace_name") as get_workspace_name,
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(primary),
        ) as get_workspace_directory,
    ):
        resolved = resolve_epic_launch_cwd(
            project_dir,
            agent_project_file=project_file,
        )

    assert resolved == primary
    get_workspace_name.assert_not_called()
    get_workspace_directory.assert_called_once_with("gh_sase-org__sase", 1)


def test_resolve_epic_launch_cwd_accepts_project_file_without_project_dir(
    tmp_path: Path,
) -> None:
    project_file = (
        tmp_path / "projects" / "gh_sase-org__sase" / "gh_sase-org__sase.sase"
    )
    primary = tmp_path / "primary"
    primary.mkdir()

    with (
        patch("sase.workspace_provider.get_workspace_name") as get_workspace_name,
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(primary),
        ) as get_workspace_directory,
    ):
        resolved = resolve_epic_launch_cwd(
            None,
            agent_project_file=project_file,
        )

    assert resolved == primary
    get_workspace_name.assert_not_called()
    get_workspace_directory.assert_called_once_with("gh_sase-org__sase", 1)


def test_resolve_epic_launch_cwd_requires_a_project_signal() -> None:
    with pytest.raises(ValueError, match="project_dir or agent_project_file"):
        resolve_epic_launch_cwd(None)


@pytest.mark.parametrize("provider_name", ["sase", None])
def test_resolve_epic_launch_cwd_canonicalizes_compatibility_fallback(
    tmp_path: Path,
    provider_name: str | None,
) -> None:
    project_dir = tmp_path / "sase_10"
    primary = tmp_path / "primary"
    primary.mkdir()

    with (
        patch(
            "sase.workspace_provider.get_workspace_name",
            return_value=provider_name,
        ),
        patch(
            "sase.project_aliases.resolve_project_alias_ref",
            return_value="gh_sase-org__sase",
        ) as resolve_alias,
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(primary),
        ) as get_workspace_directory,
    ):
        resolved = resolve_epic_launch_cwd(project_dir)

    assert resolved == primary
    resolve_alias.assert_called_once_with("sase")
    get_workspace_directory.assert_called_once_with("gh_sase-org__sase", 1)


def test_resolve_epic_launch_cwd_rejects_invalid_project_file_identity(
    tmp_path: Path,
) -> None:
    with (
        patch("sase.workspace_provider.get_workspace_name") as get_workspace_name,
        patch("sase.running_field.get_workspace_directory") as get_workspace_directory,
        pytest.raises(ValueError, match="does not identify a valid SASE project"),
    ):
        resolve_epic_launch_cwd(
            tmp_path / "sase_10",
            agent_project_file="project.sase",
        )

    get_workspace_name.assert_not_called()
    get_workspace_directory.assert_not_called()


def test_submit_epic_launch_task_submits_literal_detached_command(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "auth rewrite.md"
    task = SimpleNamespace(
        task_id="k7m2xyz",
        kind="detached",
        session_id=None,
    )
    with (
        patch("sase.tasks.tasks_dir", return_value=tmp_path / "tasks"),
        patch("sase.tasks.read_tasks", return_value=[]),
        patch(
            "sase.bead.project_name.infer_project_name_from_cwd",
            return_value="sase",
        ),
        patch(
            "sase.tasks.runner.submit_detached_task",
            return_value=task,
        ) as submit_task,
    ):
        submitted = submit_epic_launch_task(
            plan,
            cwd=tmp_path,
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            origin="ace",
        )

    assert submitted is task
    assert submit_task.call_args.args[0] == [
        "sase",
        "bead",
        "work",
        str(plan),
        "--yes-to-all",
        "--artifacts-dir",
        str(tmp_path / "artifacts"),
        "--cl-name",
        "demo",
    ]
    kwargs = submit_task.call_args.kwargs
    assert kwargs["label"] == "Epic launch · auth rewrite"
    assert kwargs["cwd"] == tmp_path
    assert kwargs["origin"] == "ace"
    assert kwargs["project"] == "sase"
    assert kwargs["cl_name"] == "demo"
    assert sorted(kwargs["tags"]) == ["epic", "launch"]
    assert "session_id" not in kwargs


def test_submit_epic_launch_task_deduplicates_active_resolved_plan(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plans" / "epic.md"
    existing = SimpleNamespace(
        task_id="existing",
        command=["sase", "bead", "work", "plans/epic.md", "--yes-to-all"],
        cwd=str(tmp_path),
        tags=["epic", "launch"],
    )
    with (
        patch("sase.tasks.tasks_dir", return_value=tmp_path / "tasks"),
        patch("sase.tasks.read_tasks", return_value=[existing]) as read_tasks,
        patch(
            "sase.bead.project_name.infer_project_name_from_cwd",
            return_value="sase",
        ),
        patch("sase.tasks.runner.submit_detached_task") as submit_task,
    ):
        submitted = submit_epic_launch_task(plan, cwd=tmp_path)

    assert submitted is existing
    read_tasks.assert_called_once()
    assert read_tasks.call_args.kwargs["status"] == frozenset({"pending", "running"})
    assert read_tasks.call_args.kwargs["kind"] == "detached"
    submit_task.assert_not_called()


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
            started_at="2026-07-15T12:00:00+00:00",
        )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta == {
        "name": "planner",
        "epic_bead_id": "sase-64",
        "epic_started_at": "2026-07-15T12:00:00+00:00",
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
