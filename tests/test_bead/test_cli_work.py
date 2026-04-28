"""Integration tests for the ``sase bead work`` CLI handler."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.xprompt.workflow_models import Workflow


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Create a fresh beads project and route the CLI's lookups at it."""
    with BeadProject.init(tmp_path):
        pass
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)
    yield tmp_path


@pytest.fixture(autouse=True)
def fake_xprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub xprompt resolution so tests don't depend on the loader's chain."""
    work_phase = Workflow(name="bd/work_phase_bead")
    land_epic = Workflow(name="bd/land_epic")
    monkeypatch.setattr(
        "sase.bead.xprompts.resolve_work_phase_xprompt",
        lambda project=None: work_phase,
    )
    monkeypatch.setattr(
        "sase.bead.xprompts.resolve_land_epic_xprompt",
        lambda project=None: land_epic,
    )


class FakeLaunchResult:
    def __init__(self) -> None:
        self.pid = 4242
        self.workspace_num = 7
        self.workspace_dir = "/tmp/fake_workspace"
        self.output_path = "/tmp/fake_output"


def _seed_diamond(project_dir: Path) -> tuple[str, list[str]]:
    """Seed a diamond DAG: p1 → {p2, p3} → p4. Returns (epic_id, phase_ids)."""
    with BeadProject(project_dir) as proj:
        epic = proj.create("Diamond epic", IssueType.PLAN)
        p1 = proj.create("P1", IssueType.PHASE, parent_id=epic.id)
        p2 = proj.create("P2", IssueType.PHASE, parent_id=epic.id)
        p3 = proj.create("P3", IssueType.PHASE, parent_id=epic.id)
        p4 = proj.create("P4", IssueType.PHASE, parent_id=epic.id)
        proj.add_dependency(p2.id, p1.id)
        proj.add_dependency(p3.id, p1.id)
        proj.add_dependency(p4.id, p2.id)
        proj.add_dependency(p4.id, p3.id)
        return epic.id, [p1.id, p2.id, p3.id, p4.id]


def _make_args(epic_id: str, *, dry_run: bool = False, yes: bool = False) -> Any:
    return argparse.Namespace(id=epic_id, dry_run=dry_run, yes=yes)


def test_work_launches_and_passes_rendered_multi_prompt(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = _seed_diamond(project_dir)
    captured: dict[str, Any] = {}

    def fake_launch(query: str, extra_env: Any = None) -> FakeLaunchResult:
        captured["query"] = query
        captured["extra_env"] = extra_env
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(_make_args(epic_id, yes=True))

    # Launcher was called exactly once with a multi-prompt referencing every phase.
    query = captured["query"]
    assert "---" in query
    for pid in phase_ids:
        assert f"#bd/work_phase_bead:{pid}" in query
    assert f"#bd/land_epic:{epic_id}" in query

    # Each phase was pre-claimed (status=in_progress, assignee=epic_<epic>_p<pid>).
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
    epic_id, phase_ids = _seed_diamond(project_dir)
    launch_calls: list[str] = []

    def fake_launch(query: str, extra_env: Any = None) -> FakeLaunchResult:
        launch_calls.append(query)
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(_make_args(epic_id, dry_run=True, yes=True))

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


def test_work_rolls_back_on_launch_failure(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = _seed_diamond(project_dir)

    def boom(query: str, extra_env: Any = None) -> FakeLaunchResult:
        raise RuntimeError("workspace claim failed")

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", boom)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(_make_args(epic_id, yes=True))
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


def test_work_rejects_already_ready_epic(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _ = _seed_diamond(project_dir)
    with BeadProject(project_dir) as proj:
        proj.mark_ready_to_work(epic_id)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(_make_args(epic_id, yes=True))
    assert excinfo.value.code == 1
    assert "already marked is_ready_to_work" in capsys.readouterr().err


def test_work_rejects_non_plan_bead(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, phase_ids = _seed_diamond(project_dir)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(_make_args(phase_ids[0], yes=True))
    assert excinfo.value.code == 1
    assert "only applies to plan beads" in capsys.readouterr().err


def _write_orphan_meta(home: Path, name: str) -> Path:
    """Write a fake live agent_meta.json under ``home/.sase/projects/...``."""
    artifact_dir = (
        home
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / f"orphan-{name}"
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"name": name, "pid": os.getpid(), "model": "test"})
    )
    return artifact_dir


def test_work_refuses_when_phase_name_collision(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = _seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    orphan_dir = _write_orphan_meta(fake_home, phase_ids[0])
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: launch_calls.append(query) or FakeLaunchResult(),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(_make_args(epic_id, yes=True))
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "refusing to launch" in err
    assert phase_ids[0] in err
    assert str(orphan_dir) in err
    assert launch_calls == []

    # Pre-claims and ready flag must not have been touched.
    with BeadProject(project_dir) as proj:
        epic = proj.show(epic_id)
        assert epic.is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN


def test_work_refuses_when_land_name_collision(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _ = _seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    _write_orphan_meta(fake_home, f"{epic_id}.land")
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: FakeLaunchResult(),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(_make_args(epic_id, yes=True))
    assert excinfo.value.code == 1
    assert f"{epic_id}.land" in capsys.readouterr().err


def test_work_dry_run_warns_on_collision_without_mutating(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = _seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    _write_orphan_meta(fake_home, phase_ids[0])
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: launch_calls.append(query) or FakeLaunchResult(),
    )

    bead_cli.handle_bead_work(_make_args(epic_id, dry_run=True, yes=True))

    captured = capsys.readouterr()
    assert "would block live launch" in captured.err
    assert phase_ids[0] in captured.err
    assert "Multi-prompt (dry run)" in captured.out
    assert launch_calls == []

    with BeadProject(project_dir) as proj:
        epic = proj.show(epic_id)
        assert epic.is_ready_to_work is False
        for pid in phase_ids:
            assert proj.show(pid).status == Status.OPEN


def test_work_passes_when_no_collisions(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    epic_id, _ = _seed_diamond(project_dir)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    captured: dict[str, Any] = {}

    def fake_launch(query: str, extra_env: Any = None) -> FakeLaunchResult:
        captured["query"] = query
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(_make_args(epic_id, yes=True))
    assert "---" in captured["query"]


def test_rollback_kills_partially_launched_agents(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agent.launcher import AgentLaunchResult
    from sase.agent.multi_prompt_launcher import MultiPromptPartialLaunchError

    epic_id, _ = _seed_diamond(project_dir)

    # Spawn a real, harmless child so we can observe SIGTERM.
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
            raise MultiPromptPartialLaunchError([partial_result], RuntimeError("boom"))

        monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

        with pytest.raises(SystemExit) as excinfo:
            bead_cli.handle_bead_work(_make_args(epic_id, yes=True))
        assert excinfo.value.code == 1

        # The child should have received SIGTERM and exited; poll briefly.
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
