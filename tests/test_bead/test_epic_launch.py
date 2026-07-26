"""Shared approved-epic launch helper tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.bead.epic_launch import (
    TASK_LOG_PATH_ENV,
    _run_detached_worker,
    build_epic_launch_argv,
    parse_epic_launch_output,
    resolve_epic_launch_cwd,
    submit_epic_launch_task,
    update_epic_launch_metadata,
)


def test_build_and_parse_epic_launch_contract() -> None:
    assert build_epic_launch_argv("/tmp/epic plan.md") == [
        "sase",
        "bead",
        "work",
        "/tmp/epic plan.md",
        "--yes-to-all",
    ]
    parsed = parse_epic_launch_output(
        "✓ Archived        /plans/202607/epic plan.md (committed)\n"
        "✓ Plan linked     bead_id: sase-64 · /plans/202607/epic plan.md\n"
        "Epic: sase-64\n"
    )
    assert parsed.epic_id == "sase-64"
    assert parsed.archived_plan_path == "/plans/202607/epic plan.md"


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


def test_submit_epic_launch_task_submits_worker_argv(tmp_path: Path) -> None:
    task = SimpleNamespace(task_id="k7m2xyz")
    with (
        patch("sase.tasks.runner.submit_task", return_value=task) as submit_task,
        patch(
            "sase.bead.epic_launch._epic_launch_session_id",
            return_value="20260725T120000Z-99",
        ),
    ):
        submitted = submit_epic_launch_task(
            tmp_path / "auth rewrite.md",
            cwd=tmp_path,
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
        )

    assert submitted is task
    argv = submit_task.call_args.args[0]
    assert argv[1:4] == ["-m", "sase.bead.epic_launch", "--worker"]
    assert argv[4:8] == [
        "--plan-file",
        str(tmp_path / "auth rewrite.md"),
        "--cwd",
        str(tmp_path),
    ]
    assert "--log-path" not in argv
    assert argv[-2:] == ["--cl-name", "demo"]
    kwargs = submit_task.call_args.kwargs
    assert kwargs["label"] == "Epic launch · auth rewrite"
    assert kwargs["cwd"] == tmp_path
    assert kwargs["origin"] == "epic-launch"
    assert kwargs["cl_name"] == "demo"
    assert kwargs["session_id"] == "20260725T120000Z-99"
    assert sorted(kwargs["tags"]) == ["epic", "launch"]


def test_submit_epic_launch_task_attributes_the_resolved_session(
    tmp_path: Path,
) -> None:
    identity = SimpleNamespace(session_id="20260725T120000Z-7")
    with (
        patch("sase.tasks.runner.submit_task") as submit_task,
        patch("sase.sessions.resolve_session_ref", return_value=identity) as resolve,
    ):
        submit_epic_launch_task(tmp_path / "plan.md", cwd=tmp_path)

    resolve.assert_called_once_with(None)
    assert submit_task.call_args.kwargs["session_id"] == "20260725T120000Z-7"


def test_submit_epic_launch_task_runs_unattributed_without_a_session(
    tmp_path: Path,
) -> None:
    with (
        patch("sase.tasks.runner.submit_task") as submit_task,
        patch("sase.sessions.resolve_session_ref", side_effect=RuntimeError("boom")),
    ):
        submit_epic_launch_task(tmp_path / "plan.md", cwd=tmp_path)

    assert submit_task.call_args.kwargs["session_id"] is None


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
        update_epic_launch_metadata(
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


def test_detached_worker_inherits_output_and_reports_the_task_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_log = tmp_path / "logs" / "k7m2ab.log"
    task_log.parent.mkdir(parents=True)
    task_log.write_text(
        "Epic: sase-77\n  Plan linked bead_id: sase-77 · /plans/epic.md\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(TASK_LOG_PATH_ENV, str(task_log))
    args = SimpleNamespace(
        plan_file=str(tmp_path / "plan.md"),
        cwd=str(tmp_path),
        log_path=None,
        artifacts_dir=None,
        cl_name="demo",
    )
    with (
        patch(
            "sase.bead.epic_launch.subprocess.run",
            return_value=SimpleNamespace(returncode=0),
        ) as run,
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        returncode = _run_detached_worker(args)

    assert returncode == 0
    # The supervisor owns the output, so the worker must not redirect it.
    assert "stdout" not in run.call_args.kwargs
    assert "stderr" not in run.call_args.kwargs
    assert notify.call_args.kwargs["extra_files"] == [str(task_log)]
    assert notify.call_args.args[2] is True
    assert f"Launch log: {task_log}" in notify.call_args.args[3]


def test_detached_worker_reports_command_start_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TASK_LOG_PATH_ENV, raising=False)
    log_path = tmp_path / "epic.log"
    args = SimpleNamespace(
        plan_file=str(tmp_path / "plan.md"),
        cwd=str(tmp_path),
        log_path=str(log_path),
        artifacts_dir=None,
        cl_name="demo",
    )
    with (
        patch(
            "sase.bead.epic_launch.subprocess.run",
            side_effect=OSError("missing sase"),
        ),
        patch("sase.bead.epic_launch._notify_detached_completion") as notify,
    ):
        returncode = _run_detached_worker(args)

    assert returncode == 1
    assert "missing sase" in log_path.read_text(encoding="utf-8")
    assert notify.call_args.kwargs["returncode"] == -1
