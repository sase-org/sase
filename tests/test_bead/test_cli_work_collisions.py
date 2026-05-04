"""Name-collision coverage for ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Status
from sase.bead.project import BeadProject

from .cli_work_helpers import (
    FakeLaunchResult,
    make_args,
    seed_diamond,
    write_orphan_meta,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_work_retry_allows_terminal_same_name_attempt(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    write_orphan_meta(fake_home, phase_ids[0], done=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    captured: dict[str, Any] = {}

    def fake_launch(query: str, extra_env: Any = None) -> FakeLaunchResult:
        captured["query"] = query
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert f"#bd/work_phase_bead:{phase_ids[0]}" in captured["query"]


def test_work_retry_refuses_live_same_name_attempt(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    orphan_dir = write_orphan_meta(fake_home, phase_ids[0])
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: launch_calls.append(query) or FakeLaunchResult(),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "refusing to launch" in err
    assert "still live" in err
    assert phase_ids[0] in err
    assert str(orphan_dir) in err
    assert launch_calls == []

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
    epic_id, _ = seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    write_orphan_meta(fake_home, f"{epic_id}")
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: FakeLaunchResult(),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    assert excinfo.value.code == 1
    assert f"{epic_id}" in capsys.readouterr().err


def test_work_refuses_when_legacy_land_name_collision(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _ = seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    write_orphan_meta(fake_home, f"{epic_id}.land")
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: FakeLaunchResult(),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    assert excinfo.value.code == 1
    assert f"{epic_id}.land" in capsys.readouterr().err


def test_work_dry_run_warns_on_collision_without_mutating(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    write_orphan_meta(fake_home, phase_ids[0])
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: launch_calls.append(query) or FakeLaunchResult(),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

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


def test_work_dry_run_retry_filters_closed_phases_without_mutating(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None: launch_calls.append(query) or FakeLaunchResult(),
    )

    with BeadProject(project_dir) as proj:
        proj.mark_ready_to_work(epic_id)
        proj.close([phase_ids[0]])
        proj.update(phase_ids[1], status="in_progress", assignee="previous")

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    assert launch_calls == []
    captured = capsys.readouterr()
    assert "already ready; retrying remaining non-closed phases" in captured.out
    assert f"#bd/work_phase_bead:{phase_ids[0]}" not in captured.out
    for pid in phase_ids[1:]:
        assert f"#bd/work_phase_bead:{pid}" in captured.out

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is True
        assert proj.show(phase_ids[0]).status == Status.CLOSED
        p2 = proj.show(phase_ids[1])
        assert p2.status == Status.IN_PROGRESS
        assert p2.assignee == "previous"
        for pid in phase_ids[2:]:
            assert proj.show(pid).status == Status.OPEN


def test_work_passes_when_no_collisions(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    epic_id, _ = seed_diamond(project_dir)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    captured: dict[str, Any] = {}

    def fake_launch(query: str, extra_env: Any = None) -> FakeLaunchResult:
        captured["query"] = query
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    assert "---" in captured["query"]
