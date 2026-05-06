"""Integration tests for the epic ``sase bead work`` CLI handler."""

from __future__ import annotations

import signal
import subprocess
import sys
import time
import json
from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import BeadProject
from sase.axe.artifact_metadata import SASE_AGENT_WORKFLOW_LINKS_ENV

from .cli_work_helpers import (
    FakeLaunchResult,
    make_args,
    seed_changespec_epic,
    seed_diamond,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_work_launches_and_passes_rendered_multi_prompt(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    captured: dict[str, Any] = {}

    def fake_launch(query: str, extra_env: Any = None) -> FakeLaunchResult:
        captured["query"] = query
        captured["extra_env"] = extra_env
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    # Launcher was called exactly once with a multi-prompt referencing every phase.
    query = captured["query"]
    assert "---" in query
    assert query.count(f"%tag:{epic_id}") == len(phase_ids) + 1
    for pid in phase_ids:
        assert f"#bd/work_phase_bead:{pid}" in query
    assert f"#bd/land_epic:{epic_id}" in query
    links = json.loads(captured["extra_env"][SASE_AGENT_WORKFLOW_LINKS_ENV])
    assert links["*"]["epic_bead_id"] == epic_id
    for pid in phase_ids:
        assert links[pid]["phase_bead_id"] == pid
        assert links[pid]["epic_bead_id"] == epic_id
    assert links[epic_id]["bead_id"] == epic_id

    # Each phase was pre-claimed.
    with BeadProject(project_dir) as proj:
        epic = proj.show(epic_id)
        assert epic.is_ready_to_work is True
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.IN_PROGRESS
            assert phase.assignee == pid

    out = capsys.readouterr().out
    assert "Launched" in out


def test_work_dry_run_never_mutates_or_launches(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    launch_calls: list[str] = []

    def fake_launch(query: str, extra_env: Any = None) -> FakeLaunchResult:
        launch_calls.append(query)
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    assert launch_calls == []
    with BeadProject(project_dir) as proj:
        epic = proj.show(epic_id)
        assert epic.is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""

    out = capsys.readouterr().out
    assert "Multi-prompt (dry run)" in out
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in out
    assert out.count(f"%tag:{epic_id}") == len(phase_ids) + 1


def test_work_dry_run_regular_epic_renders_vcs_launch_wrappers(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = tmp_path / "home"
    project_root = fake_home / ".sase" / "projects" / "sase"
    project_root.mkdir(parents=True)
    (project_root / "sase.gp").write_text(
        "WORKSPACE_DIR: /tmp/sase\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda: "sase",
    )
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda project_file: "git",
    )

    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: launch_calls.append(query) or FakeLaunchResult(),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    assert launch_calls == []
    out = capsys.readouterr().out
    for pid in phase_ids:
        assert f"#git:sase\n%name:{pid}\n%tag:{epic_id}" in out
        assert f"#bd/work_phase_bead:{pid}" in out
    assert f"#git:sase\n%name:{epic_id}\n%tag:{epic_id}" in out
    assert f"#bd/land_epic:{epic_id}" in out
    assert out.count(f"%tag:{epic_id}") == len(phase_ids) + 1

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


def test_work_dry_run_renders_changespec_launch_wrappers(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_changespec_epic(project_dir)
    fake_home = tmp_path / "home"
    project_root = fake_home / ".sase" / "projects" / "sase"
    project_root.mkdir(parents=True)
    (project_root / "sase.gp").write_text(
        "WORKSPACE_DIR: /tmp/sase\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda: "sase",
    )
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda project_file: "git",
    )

    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: launch_calls.append(query) or FakeLaunchResult(),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    assert launch_calls == []
    out = capsys.readouterr().out
    assert "#git:sase #pr(name=feature_epic, bug_id=12345)" in out
    assert (
        f"#git:sase #pr(name=feature_epic, bug_id=12345)\n%name:{phase_ids[0]}\n%tag:{epic_id}"
        in out
    )
    assert f"#git:feature_epic\n%name:{phase_ids[1]}\n%tag:{epic_id}" in out
    assert f"#git:feature_epic\n%name:{epic_id}\n%tag:{epic_id}" in out
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in out
    assert f"#bd/land_epic:{epic_id}" in out
    assert out.count(f"%tag:{epic_id}") == len(phase_ids) + 1

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


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


def test_work_rolls_back_on_launch_failure(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    def boom(query: str, extra_env: Any = None) -> FakeLaunchResult:
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
    assert "Rolling back" in err


def test_work_allows_already_ready_epic_and_launches_remaining_phases(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    captured: dict[str, Any] = {}

    def fake_launch(query: str, extra_env: Any = None) -> FakeLaunchResult:
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
        for pid in phase_ids[1:]:
            phase = proj.show(pid)
            assert phase.status == Status.IN_PROGRESS
            assert phase.assignee == pid

    out = capsys.readouterr().out
    assert "already ready; retrying remaining non-closed phases" in out


def test_work_retry_does_not_unmark_already_ready_epic_on_launch_failure(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    def boom(query: str, extra_env: Any = None) -> FakeLaunchResult:
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
    assert "Rolling back pre-claims" in err


def test_work_rollback_restores_prior_in_progress_status(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    def boom(query: str, extra_env: Any = None) -> FakeLaunchResult:
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
    assert "only applies to epic or legend plan beads" in capsys.readouterr().err


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
    )
    try:
        partial_result = AgentLaunchResult(
            pid=child.pid,
            workspace_num=0,
            workspace_dir="",
            output_path="",
        )

        def fake_launch(query: str, extra_env: Any = None) -> Any:
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
    assert "Rolling back" in err
