"""Lifecycle, rollback, and validation tests for epic ``sase bead work``."""

from __future__ import annotations

from contextlib import contextmanager
import json
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
    events: list[str] = []

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            events.append("launch") or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: events.append("commit") or True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.bead_state_is_clean",
        lambda _beads_dir: True,
    )

    def fake_push(beads_dir: Path) -> _PushOutcome:
        assert beads_dir == project_dir / "sdd/beads"
        events.append("push")
        return _PushOutcome(pushed=True, skipped_no_remote=False, error=None)

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_push)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": True}},
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert events == ["commit", "push", "launch"]
    out = capsys.readouterr().out
    assert f"Committed epic launch checkpoint for {epic_id}." in out
    assert "Pushed to remote." in out


def test_work_uses_sync_push_even_when_config_flag_disabled(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _ = seed_diamond(project_dir)

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )
    pushes: list[Path] = []
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda beads_dir: (
            pushes.append(beads_dir)
            or type(
                "Outcome",
                (),
                {"pushed": True, "skipped_no_remote": False, "error": None},
            )()
        ),
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": False}},
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert pushes == [project_dir / "sdd/beads"]
    out = capsys.readouterr().out
    assert f"Committed epic launch checkpoint for {epic_id}." in out
    assert "Pushed to remote." in out


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
    assert f"Committed epic launch checkpoint for {epic_id}." in out
    assert "Pushed to remote." not in out
    assert "background" not in out


def test_work_no_push_rejects_detached_store_before_launch(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    launches: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_commit._requires_remote_publication",
        lambda _beads_dir: True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr("sase.bead.sync.bead_state_is_clean", lambda _path: True)
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launches.append(query) or FakeLaunchResult()
        ),
    )

    with pytest.raises(SystemExit):
        bead_cli.handle_bead_work(
            make_args(epic_id, yes=True, no_push=True),
        )

    assert launches == []
    assert "--no-push cannot launch workers" in capsys.readouterr().err
    with BeadProject(project_dir) as project:
        assert project.show(epic_id).is_ready_to_work is True
        assert project.show(epic_id).assignee == f"{epic_id}.land"
        assert [project.show(phase_id).assignee for phase_id in phase_ids] == phase_ids


def test_work_async_config_is_upgraded_to_sync_prelaunch_push(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _ = seed_diamond(project_dir)
    events: list[str] = []

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            events.append("launch") or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"push_after_commit": "async"}},
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda beads_dir: (
            events.append("sync-push")
            or type(
                "Outcome",
                (),
                {"pushed": True, "skipped_no_remote": False, "error": None},
            )()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch_async",
        lambda beads_dir: pytest.fail("epic checkpoint must never push async"),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert events == ["sync-push", "launch"]
    out = capsys.readouterr().out
    assert f"Committed epic launch checkpoint for {epic_id}." in out
    assert "Pushed to remote." in out
    assert "background" not in out


def test_work_push_failure_stops_before_launch_and_preserves_checkpoint(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.bead.sync import _PushOutcome

    epic_id, _ = seed_diamond(project_dir)
    launches: list[str] = []

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launches.append(query) or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr("sase.bead.sync.bead_state_is_clean", lambda _path: True)
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

    with pytest.raises(SystemExit):
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    captured = capsys.readouterr()
    assert "Launched" not in captured.out
    assert launches == []
    assert "git push failed: nope" in captured.err
    with BeadProject(project_dir) as project:
        assert project.show(epic_id).is_ready_to_work is True
        assert project.show(epic_id).status is Status.IN_PROGRESS


def test_work_retry_push_failure_preserves_existing_checkpoint(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.sync import _PushOutcome, bead_state_is_clean
    from sase.bead.work import build_epic_work_plan_from_beads_dir

    epic_id, phase_ids = seed_diamond(project_dir)
    with BeadProject(project_dir) as project:
        project.mark_ready_to_work(epic_id)
        plan = build_epic_work_plan_from_beads_dir(project.beads_dir, epic_id)
        project.preclaim_epic_work(
            epic_id,
            [
                (assignment.bead_id, assignment.agent_name)
                for wave in plan.waves
                for assignment in wave
            ],
            plan.land_agent_name,
        )
        assert bead_state_is_clean(project.beads_dir)

    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr("sase.bead.sync.bead_state_is_clean", lambda _path: True)
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda _beads_dir: _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error="git push failed: retry",
        ),
    )
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda *_args, **_kwargs: pytest.fail("failed retry must not spawn"),
    )

    with pytest.raises(SystemExit):
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    with BeadProject(project_dir) as project:
        assert project.show(epic_id).is_ready_to_work is True
        assert project.show(epic_id).assignee == f"{epic_id}.land"
        assert [project.show(phase_id).assignee for phase_id in phase_ids] == phase_ids


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


def test_work_checkpoint_failure_rolls_back_before_launch(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.bead.sync import BeadWorkLaunchCommitError

    epic_id, phase_ids = seed_diamond(project_dir)

    launches: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launches.append(query) or FakeLaunchResult()
        ),
    )

    def boom(*args: Any, **kwargs: Any) -> bool:
        raise BeadWorkLaunchCommitError("git commit failed")

    monkeypatch.setattr("sase.bead.sync.commit_epic_graph_checkpoint", boom)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    assert excinfo.value.code == 1

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""

    captured = capsys.readouterr()
    assert "Launched" not in captured.out
    assert launches == []
    assert "checkpoint failed before agent launch" in captured.err
    assert "git commit failed" in captured.err


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
        assert reassigned.assignee == phase_ids[1]
        for pid in phase_ids[2:]:
            phase = proj.show(pid)
            assert phase.status == Status.IN_PROGRESS
            assert phase.assignee == pid
        epic = proj.show(epic_id)
        assert epic.status == Status.IN_PROGRESS
        assert epic.assignee == f"{epic_id}.land"

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


def test_work_missing_bead_json_error_is_one_envelope(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args("sase-missing", json_output=True))

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "ok": False,
        "mode": "bead_id",
        "epic_id": "sase-missing",
        "error": "issue not found: sase-missing",
    }


def test_work_non_plan_bead_json_error_is_one_envelope(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, phase_ids = seed_diamond(project_dir)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(phase_ids[0], json_output=True))

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["mode"] == "bead_id"
    assert payload["epic_id"] == phase_ids[0]
    assert payload["error"].startswith("sase bead work only applies to plan beads")


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


def test_work_plain_plan_tier_json_error_is_one_envelope(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        plan = proj.create("Plain plan", IssueType.PLAN, tier=BeadTier.PLAN)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(plan.id, json_output=True))

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "ok": False,
        "mode": "bead_id",
        "epic_id": plan.id,
        "error": (
            f"sase bead work only applies to epic plan beads (got plan for {plan.id})"
        ),
    }


def test_bead_id_launch_uses_epic_lock_and_reports_only_phase_children(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Parent epic", IssueType.PLAN, tier=BeadTier.EPIC)
        phase = proj.create("Real phase", IssueType.PHASE, parent_id=epic.id)
        proj.create(
            "Nested epic",
            IssueType.PLAN,
            parent_id=epic.id,
            tier=BeadTier.EPIC,
        )

    lock_depth = 0
    lock_roots: list[Path] = []

    @contextmanager
    def fake_launch_lock(repo_root: Path):
        nonlocal lock_depth
        lock_roots.append(repo_root)
        lock_depth += 1
        try:
            yield
        finally:
            lock_depth -= 1

    def fake_launch(*_args: object, **_kwargs: object) -> bool:
        assert lock_depth == 1
        return True

    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan_store.epic_plan_launch_lock",
        fake_launch_lock,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        fake_launch,
    )

    bead_cli.handle_bead_work(make_args(epic.id, json_output=True))

    payload = json.loads(capsys.readouterr().out)
    assert payload["phase_bead_ids"] == [phase.id]
    assert lock_roots == [project_dir]


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
    assert "preserving is_ready_to_work and all epic work preclaims" in err
    with BeadProject(project_dir) as project:
        epic = project.show(epic_id)
        assert epic.is_ready_to_work is True
        assert epic.status == Status.IN_PROGRESS
        assert epic.assignee == f"{epic_id}.land"
