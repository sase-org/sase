"""Standalone task-bead ``sase bead work`` lifecycle tests."""

from __future__ import annotations

import json
import shutil
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_work_cleanup import CleanupPreview, CleanupTarget
from sase.bead.cli_work_commit import (
    TaskLaunchCheckpointError,
    checkpoint_task_work_launch,
)
from sase.bead.model import PhaseSize, Status
from sase.bead.project import BeadProject
from sase.bead.work import SASE_BEAD_ID_ENV, VCSLaunchContext

from .cli_work_helpers import FakeLaunchResult, make_args, seed_task

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


@pytest.fixture(autouse=True)
def task_vcs_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_work_task.resolve_task_vcs_launch_context",
        lambda: VCSLaunchContext(vcs_workflow="git", project_name="sase"),
    )


def test_task_checkpoint_commits_and_pushes_before_return(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.sync import _PushOutcome

    task_id = seed_task(project_dir)
    events: list[str] = []

    class Timer:
        def stage(self, *_args: object, **_kwargs: object) -> Any:
            return nullcontext()

    monkeypatch.setattr(
        "sase.bead.sync.commit_task_work_launch",
        lambda *_args, **_kwargs: events.append("commit") or True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.bead_state_is_clean",
        lambda _path: True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda _path, **_kwargs: (
            events.append("push")
            or _PushOutcome(pushed=True, skipped_no_remote=False, error=None)
        ),
    )

    checkpoint_task_work_launch(
        project_dir / "sdd/beads",
        task_id,
        no_push=False,
        timer=Timer(),  # type: ignore[arg-type]
    )

    assert events == ["commit", "push"]


def test_task_checkpoint_reports_contention_timeout_before_no_remote(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.sync import _PushOutcome

    task_id = seed_task(project_dir)
    log_path = project_dir / "sync.log"

    class Timer:
        def stage(self, *_args: object, **_kwargs: object) -> Any:
            return nullcontext()

    monkeypatch.setattr(
        "sase.bead.sync.commit_task_work_launch",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.bead_state_is_clean",
        lambda _path: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_commit._requires_remote_publication",
        lambda _beads_dir: True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda _path, **_kwargs: _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error=None,
            skipped_locked=True,
            log_path=log_path,
        ),
    )

    with pytest.raises(TaskLaunchCheckpointError) as excinfo:
        checkpoint_task_work_launch(
            project_dir / "sdd/beads",
            task_id,
            no_push=False,
            timer=Timer(),  # type: ignore[arg-type]
        )

    message = str(excinfo.value)
    assert "held the store lock" in message
    assert "detached bead store has no push remote" not in message
    assert f"managed sync log: {log_path}" in message


@pytest.mark.parametrize("status", [Status.OPEN, Status.READY])
def test_task_work_launches_one_checkpointed_agent(
    status: Status,
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = seed_task(project_dir, status=status)
    events: list[str] = []
    captured: dict[str, Any] = {}

    def checkpoint(*_args: object, **_kwargs: object) -> bool:
        with BeadProject(project_dir) as project:
            task = project.show(task_id)
            assert (task.status, task.assignee) == (
                Status.IN_PROGRESS,
                task_id,
            )
        events.append("checkpoint")
        return True

    def launch(
        query: str,
        *,
        segment_extra_env: tuple[dict[str, str], ...],
        expected_names: set[str],
        launch_context: VCSLaunchContext,
    ) -> list[FakeLaunchResult]:
        events.append("launch")
        captured["query"] = query
        captured["env"] = segment_extra_env
        captured["names"] = expected_names
        captured["context"] = launch_context
        return [FakeLaunchResult()]

    monkeypatch.setattr(
        "sase.bead.cli_work_task.checkpoint_task_work_launch",
        checkpoint,
    )
    monkeypatch.setattr("sase.bead.cli_work_task.launch_bead_work_agents", launch)

    bead_cli.handle_bead_work(
        make_args(
            task_id,
            yes=True,
            launch_feedback="Preserve the public API.",
        )
    )

    assert events == ["checkpoint", "launch"]
    assert captured["query"] == (
        f"#git:sase\n"
        f"%id({task_id}, bead={task_id})\n"
        f"%m:@small_worker\n"
        f"#bd/work_task:{task_id}\n"
        "Preserve the public API."
    )
    assert captured["env"][0][SASE_BEAD_ID_ENV] == task_id
    assert captured["names"] == {task_id}
    with BeadProject(project_dir) as project:
        task = project.show(task_id)
        assert (task.status, task.assignee) == (Status.IN_PROGRESS, task_id)
    assert f"✓ Launched agent {task_id} for task {task_id}" in capsys.readouterr().out


@pytest.mark.parametrize("size", [PhaseSize.LARGE, PhaseSize.XLARGE])
def test_task_work_launch_query_includes_plan_for_large_tasks(
    size: PhaseSize,
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = seed_task(project_dir, size=size)
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "sase.bead.cli_work_task.checkpoint_task_work_launch",
        lambda *_args, **_kwargs: True,
    )

    def launch(query: str, **_kwargs: object) -> list[FakeLaunchResult]:
        captured["query"] = query
        return [FakeLaunchResult()]

    monkeypatch.setattr("sase.bead.cli_work_task.launch_bead_work_agents", launch)

    bead_cli.handle_bead_work(make_args(task_id, yes=True))

    lines = captured["query"].splitlines()
    assert f"#bd/work_task:{task_id}" in lines
    assert "#plan" in lines


def test_task_work_dry_run_is_read_only(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = seed_task(project_dir)
    monkeypatch.setattr(
        "sase.bead.cli_work_task.checkpoint_task_work_launch",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not checkpoint"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.launch_bead_work_agents",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not launch"),
    )

    bead_cli.handle_bead_work(make_args(task_id, dry_run=True))

    with BeadProject(project_dir) as project:
        task = project.show(task_id)
        assert (task.status, task.assignee) == (Status.READY, "")
    output = capsys.readouterr().out
    assert "--- Task prompt (dry run) ---" in output
    assert f"#bd/work_task:{task_id}" in output


@pytest.mark.parametrize(
    ("size", "alias", "expects_plan"),
    [
        (PhaseSize.XSMALL, "@xsmall_worker", False),
        (PhaseSize.SMALL, "@small_worker", False),
        (PhaseSize.MEDIUM, "@medium_worker", False),
        (PhaseSize.LARGE, "@large_worker", True),
        (PhaseSize.XLARGE, "@xlarge_worker", True),
    ],
)
def test_task_work_dry_run_routes_all_sizes_through_phase_policy(
    size: PhaseSize,
    alias: str,
    expects_plan: bool,
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = seed_task(project_dir, size=size)

    bead_cli.handle_bead_work(make_args(task_id, dry_run=True))

    prompt = capsys.readouterr().out.split("--- Task prompt (dry run) ---\n", 1)[1]
    assert f"%m:{alias}" in prompt.splitlines()
    assert ("#plan" in prompt.splitlines()) is expects_plan
    assert "\n---\n" not in prompt


def test_task_work_dry_run_normalizes_legacy_sizeless_task_to_small(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issues_path = project.beads_dir / "issues.jsonl"
        events_dir = project.beads_dir / "events"
    legacy = {
        "id": "sase-legacy",
        "title": "Legacy sizeless task",
        "status": "ready",
        "issue_type": "task",
        "parent_id": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "dependencies": [],
    }
    issues_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    if events_dir.exists():
        shutil.rmtree(events_dir)

    bead_cli.handle_bead_work(make_args("sase-legacy", dry_run=True))

    prompt = capsys.readouterr().out.split("--- Task prompt (dry run) ---\n", 1)[1]
    assert "%m:@small_worker" in prompt.splitlines()
    assert "#plan" not in prompt.splitlines()


def test_task_work_persists_durable_stage_timing(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = seed_task(project_dir)
    timing_path = project_dir / "launch_timing.jsonl"
    monkeypatch.setenv("SASE_TUI_LAUNCH_TIMING_PATH", str(timing_path))
    monkeypatch.delenv("SASE_BEAD_WORK_TIMING", raising=False)

    bead_cli.handle_bead_work(make_args(task_id, dry_run=True))

    records = [
        json.loads(line)
        for line in timing_path.read_text(encoding="utf-8").splitlines()
    ]
    record = next(record for record in records if record["operation"] == "bead_work")
    stage_names = {stage["stage"] for stage in record["stages"]}
    assert record["operation"] == "bead_work"
    assert record["bead_id"] == task_id
    assert {
        "project_open",
        "initial_show",
        "plan_launch_lock",
        "xprompt_lookup",
        "vcs_context",
        "prompt_render",
    } <= stage_names


def test_in_progress_task_with_live_assignee_is_idempotent_success(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = seed_task(
        project_dir,
        status=Status.IN_PROGRESS,
        assignee="existing-worker",
    )
    monkeypatch.setattr(
        "sase.agent.names.get_live_agent_name_subset",
        lambda names: {"existing-worker": "/tmp/agent"} if names else {},
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.launch_bead_work_agents",
        lambda *_args, **_kwargs: pytest.fail("live task must not relaunch"),
    )

    bead_cli.handle_bead_work(make_args(task_id, yes_to_all=True))

    assert "already assigned to live agent existing-worker" in (capsys.readouterr().out)
    with BeadProject(project_dir) as project:
        task = project.show(task_id)
        assert (task.status, task.assignee) == (
            Status.IN_PROGRESS,
            "existing-worker",
        )


def test_stale_in_progress_task_cleans_up_before_mutation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = seed_task(
        project_dir,
        status=Status.IN_PROGRESS,
        assignee="dead-worker",
    )
    events: list[str] = []
    monkeypatch.setattr(
        "sase.agent.names.get_live_agent_name_subset",
        lambda _names: {},
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.prepare_bead_work_force_reuse",
        lambda query, **_kwargs: events.append("cleanup") or query.replace("!", ""),
    )

    def checkpoint(*_args: object, **_kwargs: object) -> bool:
        events.append("checkpoint")
        return True

    monkeypatch.setattr(
        "sase.bead.cli_work_task.checkpoint_task_work_launch",
        checkpoint,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.launch_bead_work_agents",
        lambda *_args, **_kwargs: events.append("launch") or [FakeLaunchResult()],
    )

    bead_cli.handle_bead_work(make_args(task_id, yes_to_all=True))

    assert events == ["cleanup", "checkpoint", "launch"]
    with BeadProject(project_dir) as project:
        task = project.show(task_id)
        assert (task.status, task.assignee) == (Status.IN_PROGRESS, task_id)


def test_yes_does_not_skip_destructive_cleanup_confirmation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = seed_task(project_dir)
    destructive = CleanupPreview(
        targets=(
            CleanupTarget(
                name=task_id,
                action="KILL",
                current_state="running",
                detail="at /tmp/agent",
            ),
        )
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.preview_bead_work_force_reuse",
        lambda *_args, **_kwargs: destructive,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.confirm_cleanup",
        lambda: False,
    )

    bead_cli.handle_bead_work(make_args(task_id, yes=True))

    with BeadProject(project_dir) as project:
        task = project.show(task_id)
        assert (task.status, task.assignee) == (Status.READY, "")


@pytest.mark.parametrize("failure_stage", ["checkpoint", "launch"])
def test_zero_spawn_failure_restores_prior_task_state(
    failure_stage: str,
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = seed_task(
        project_dir,
        status=Status.IN_PROGRESS,
        assignee="dead-worker",
    )
    monkeypatch.setattr(
        "sase.agent.names.get_live_agent_name_subset",
        lambda _names: {},
    )
    if failure_stage == "checkpoint":
        monkeypatch.setattr(
            "sase.bead.cli_work_task.checkpoint_task_work_launch",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                TaskLaunchCheckpointError("commit failed")
            ),
        )
    else:
        monkeypatch.setattr(
            "sase.bead.cli_work_task.checkpoint_task_work_launch",
            lambda *_args, **_kwargs: True,
        )
        monkeypatch.setattr(
            "sase.bead.cli_work_task.launch_bead_work_agents",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("spawn failed")
            ),
        )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(task_id, yes_to_all=True))

    assert excinfo.value.code == 1
    with BeadProject(project_dir) as project:
        task = project.show(task_id)
        assert (task.status, task.assignee) == (
            Status.IN_PROGRESS,
            "dead-worker",
        )


def test_task_work_json_reports_task_launch_state(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = seed_task(project_dir)
    monkeypatch.setattr(
        "sase.bead.cli_work_task.checkpoint_task_work_launch",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.launch_bead_work_agents",
        lambda *_args, **_kwargs: [FakeLaunchResult()],
    )

    bead_cli.handle_bead_work(make_args(task_id, json_output=True))

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "agent_name": task_id,
        "dry_run": False,
        "launch_state": "launched",
        "launched": True,
        "mode": "bead_id",
        "ok": True,
        "task_id": task_id,
        "workspace_num": 7,
    }


@pytest.mark.parametrize("status", [Status.CLAIMED, Status.CLOSED])
def test_invalid_task_status_is_rejected_without_mutation(
    status: Status,
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = seed_task(project_dir, status=status)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(task_id, yes=True))

    assert excinfo.value.code == 1
    assert f"cannot be launched from status={status.value}" in capsys.readouterr().err
