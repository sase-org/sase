"""Lifecycle, rollback, and validation tests for epic ``sase bead work``."""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import BeadProject

from .cli_work_helpers import (
    FakeLaunchResult,
    make_args,
    seed_changespec_epic,
    seed_diamond,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_work_changespec_epic_errors_without_project_context(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_changespec_epic(project_dir)
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda: None,
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    assert excinfo.value.code == 1
    assert "unable to infer the current SASE project" in capsys.readouterr().err
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            assert proj.show(pid).status == Status.OPEN


def test_work_invokes_push_when_config_flag_enabled(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.bead.sync import _PushOutcome

    epic_id, _ = seed_diamond(project_dir)
    push_calls: list[Path] = []

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: True,
    )

    def fake_push(beads_dir: Path) -> _PushOutcome:
        push_calls.append(beads_dir)
        return _PushOutcome(pushed=True, skipped_no_remote=False, error=None)

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_push)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": True}},
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert push_calls == [project_dir / "sdd/beads"]
    out = capsys.readouterr().out
    assert f"Committed bead state for epic {epic_id}." in out
    assert "Pushed to remote." in out


def test_work_skips_push_when_config_flag_disabled(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _ = seed_diamond(project_dir)

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda beads_dir: pytest.fail("push must not run when flag disabled"),
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": False}},
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    out = capsys.readouterr().out
    assert f"Committed bead state for epic {epic_id}." in out
    assert "Pushed to remote." not in out


def test_work_no_push_flag_overrides_config(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _ = seed_diamond(project_dir)

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: True,
    )
    # Config asks for a push, but --no-push wins for this invocation.
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": True}},
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda beads_dir: pytest.fail("--no-push must skip the push"),
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch_async",
        lambda beads_dir: pytest.fail("--no-push must skip the push"),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True, no_push=True))

    out = capsys.readouterr().out
    assert f"Committed bead state for epic {epic_id}." in out
    assert "Pushed to remote." not in out
    assert "background" not in out


def test_work_async_push_launches_detached_helper(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.bead.sync import _AsyncPushHandle

    epic_id, _ = seed_diamond(project_dir)
    async_calls: list[Path] = []

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": "async"}},
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda beads_dir: pytest.fail("async mode must not push synchronously"),
    )

    def fake_async(beads_dir: Path) -> _AsyncPushHandle:
        async_calls.append(beads_dir)
        return _AsyncPushHandle(pid=4321, log_path=Path("/tmp/push-test.log"))

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch_async", fake_async)

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert async_calls == [project_dir / "sdd/beads"]
    out = capsys.readouterr().out
    assert f"Committed bead state for epic {epic_id}." in out
    assert "background" in out
    assert "/tmp/push-test.log" in out


def test_work_warns_when_push_fails(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.bead.sync import _PushOutcome

    epic_id, _ = seed_diamond(project_dir)

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda beads_dir: _PushOutcome(
            pushed=False, skipped_no_remote=False, error="git push failed: nope"
        ),
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": True}},
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    captured = capsys.readouterr()
    assert f"Committed bead state for epic {epic_id}." in captured.out
    assert "Pushed to remote." not in captured.out
    assert "git push failed: nope" in captured.err


def test_work_rolls_back_on_launch_failure(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    def boom(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        raise RuntimeError("workspace claim failed")

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", boom)
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: pytest.fail("failed launch must not commit"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    assert excinfo.value.code == 1

    with BeadProject(project_dir) as proj:
        epic = proj.show(epic_id)
        assert epic.is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""

    err = capsys.readouterr().err
    assert "launch failed" in err
    assert "No agents were spawned" in err
    assert "restoring the epic's prior is_ready_to_work state" in err


def test_work_commit_failure_reports_after_successful_launch(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.bead.sync import BeadWorkLaunchCommitError

    epic_id, phase_ids = seed_diamond(project_dir)

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )

    def boom(*args: Any, **kwargs: Any) -> bool:
        raise BeadWorkLaunchCommitError("git commit failed")

    monkeypatch.setattr("sase.bead.sync.commit_bead_work_launch", boom)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    assert excinfo.value.code == 1

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is True
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""

    captured = capsys.readouterr()
    assert "Launched" in captured.out
    assert (
        f"agents launched for epic {epic_id}, but committing "
        "bead state failed: git commit failed"
    ) in captured.err


def test_work_allows_already_ready_epic_and_launches_remaining_phases(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    captured: dict[str, Any] = {}

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        captured["query"] = query
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    with BeadProject(project_dir) as proj:
        proj.mark_ready_to_work(epic_id)
        proj.close([phase_ids[0]])
        proj.update(phase_ids[1], status="in_progress", assignee="previous")

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    query = captured["query"]
    assert f"#bd/work_phase_bead:{phase_ids[0]}" not in query
    for pid in phase_ids[1:]:
        assert f"#bd/work_phase_bead:{pid}" in query

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is True
        assert proj.show(phase_ids[0]).status == Status.CLOSED
        reassigned = proj.show(phase_ids[1])
        assert reassigned.status == Status.IN_PROGRESS
        assert reassigned.assignee == "previous"
        for pid in phase_ids[2:]:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""

    out = capsys.readouterr().out
    assert "already ready; retrying remaining non-closed phases" in out


def test_work_retry_does_not_unmark_already_ready_epic_on_launch_failure(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    def boom(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        raise RuntimeError("workspace claim failed")

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", boom)

    with BeadProject(project_dir) as proj:
        proj.mark_ready_to_work(epic_id)
        proj.close([phase_ids[0]])
        proj.update(phase_ids[1], status="in_progress", assignee="previous")

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    assert excinfo.value.code == 1

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is True
        assert proj.show(phase_ids[0]).status == Status.CLOSED
        p2 = proj.show(phase_ids[1])
        assert p2.status == Status.IN_PROGRESS
        assert p2.assignee == "previous"
        for pid in phase_ids[2:]:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""

    err = capsys.readouterr().err
    assert "launch failed" in err
    assert "No agents were spawned" in err
    assert "preserving the epic's existing is_ready_to_work state" in err


def test_work_rollback_restores_prior_in_progress_status(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    def boom(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        raise RuntimeError("workspace claim failed")

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", boom)

    with BeadProject(project_dir) as proj:
        proj.update(phase_ids[0], status="in_progress", assignee="old-agent")

    with pytest.raises(SystemExit):
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    with BeadProject(project_dir) as proj:
        phase = proj.show(phase_ids[0])
        assert phase.status == Status.IN_PROGRESS
        assert phase.assignee == "old-agent"
        assert proj.show(epic_id).is_ready_to_work is False


def test_work_rejects_non_plan_bead(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, phase_ids = seed_diamond(project_dir)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(phase_ids[0], yes=True))
    assert excinfo.value.code == 1
    assert "only applies to plan beads" in capsys.readouterr().err


def test_work_rejects_plain_plan_tier(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Plain plan", IssueType.PLAN, tier=BeadTier.PLAN)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(plan.id, yes=True))
    assert excinfo.value.code == 1
    assert "only applies to epic plan beads" in capsys.readouterr().err


def test_rollback_kills_partially_launched_agents(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agent.launcher import AgentLaunchResult
    from sase.agent.multi_prompt_launcher import _MultiPromptPartialLaunchError

    epic_id, _ = seed_diamond(project_dir)

    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        partial_result = AgentLaunchResult(
            pid=child.pid,
            workspace_num=0,
            workspace_dir="",
            output_path="",
        )

        def fake_launch(
            query: str,
            extra_env: Any = None,
            segment_extra_env: Any = None,
        ) -> Any:
            with BeadProject(project_dir) as project:
                project.claim_for_agent_launch(epic_id, f"{epic_id}.land")
            raise _MultiPromptPartialLaunchError([partial_result], RuntimeError("boom"))

        monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

        with pytest.raises(SystemExit) as excinfo:
            bead_cli.handle_bead_work(make_args(epic_id, yes=True))
        assert excinfo.value.code == 1

        for _ in range(50):
            if child.poll() is not None:
                break
            time.sleep(0.1)
        assert child.poll() is not None, "partially-launched child was not killed"
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGKILL)
            child.wait(timeout=5)

    err = capsys.readouterr().err
    assert "Terminated the partially launched agents" in err
    assert "preserving is_ready_to_work and any runner-owned bead claims" in err
    with BeadProject(project_dir) as project:
        epic = project.show(epic_id)
        assert epic.is_ready_to_work is True
        assert epic.status == Status.IN_PROGRESS
        assert epic.assignee == f"{epic_id}.land"
