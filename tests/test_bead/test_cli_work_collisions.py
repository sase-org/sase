"""Name-collision coverage for ``sase bead work``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.names import AgentNameWipeResult
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


def _record_wipes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub the forced-reuse wipe and capture the names it is asked to clean."""
    wiped: list[str] = []

    def fake_wipe(name: str) -> AgentNameWipeResult:
        wiped.append(name)
        return AgentNameWipeResult(
            target_name=name,
            found=True,
            registry_names_removed=(name,),
        )

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)
    return wiped


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

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        captured["query"] = query
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert f"#bd/work_phase_bead:{phase_ids[0]}" in captured["query"]


def test_work_retry_force_reuses_live_phase_owner_and_launches(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    write_orphan_meta(fake_home, phase_ids[0])
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    wiped = _record_wipes(monkeypatch)
    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    # The live phase-name owner is force-reused instead of blocking launch.
    assert phase_ids[0] in wiped
    assert len(launch_calls) == 1
    assert "%id:!" not in launch_calls[0]

    with BeadProject(project_dir) as proj:
        epic = proj.show(epic_id)
        assert epic.is_ready_to_work is True
        for pid in phase_ids:
            assert proj.show(pid).status == Status.IN_PROGRESS


def test_work_force_reuses_live_land_owner_and_launches(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    epic_id, _ = seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    write_orphan_meta(fake_home, f"{epic_id}.land")
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    wiped = _record_wipes(monkeypatch)
    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    # The ``<epic_id>.land`` owner is force-reused, not refused.
    assert f"{epic_id}.land" in wiped
    assert len(launch_calls) == 1


def test_work_force_reuses_legacy_land_owner_and_launches(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    epic_id, _ = seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    write_orphan_meta(fake_home, epic_id)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    wiped = _record_wipes(monkeypatch)
    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    # The legacy ``<epic_id>`` owner is an extra cleanup target even though
    # it is not rendered as a %id:! directive in the new prompt.
    assert epic_id in wiped
    assert len(launch_calls) == 1


def test_work_dry_run_warns_force_reuse_without_mutating(
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
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    captured = capsys.readouterr()
    assert "would be force-reused" in captured.err
    assert phase_ids[0] in captured.err
    assert "Multi-prompt (dry run)" in captured.out
    assert launch_calls == []

    with BeadProject(project_dir) as proj:
        epic = proj.show(epic_id)
        assert epic.is_ready_to_work is False
        for pid in phase_ids:
            assert proj.show(pid).status == Status.OPEN


def test_work_force_reuses_workflow_name_only_owner(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The land name can be reserved as a *workflow_name* of an unrelated agent.

    Reproduces the ``sase-4q`` class: a completed ``home`` agent family whose
    artifact ``name`` is ``<epic_id>.land--code`` but whose ``workflow_name`` is
    the plan's land name (``<epic_id>.land``). Relaunch must wipe that owner before
    the launcher's permanent-name validation runs.
    """
    epic_id, _ = seed_diamond(project_dir)

    fake_home = tmp_path / "fake_home"
    artifact_dir = (
        fake_home
        / ".sase"
        / "projects"
        / "home"
        / "artifacts"
        / "ace-run"
        / "20260101000000"
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": f"{epic_id}.land--code",
                "workflow_name": f"{epic_id}.land",
                "model": "test",
            }
        )
    )
    (artifact_dir / "done.json").write_text(
        json.dumps({"name": f"{epic_id}.land--code", "outcome": "completed"})
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    from sase.agent.names import is_name_reserved, rebuild_name_registry

    rebuild_name_registry()
    assert is_name_reserved(f"{epic_id}.land")

    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert len(launch_calls) == 1
    assert "%id:!" not in launch_calls[0]
    # The workflow_name-only owner is gone after the forced-reuse cleanup.
    assert not is_name_reserved(f"{epic_id}.land")
    assert not artifact_dir.exists()


def test_work_dry_run_retry_filters_closed_phases_without_mutating(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)

    launch_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
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

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        captured["query"] = query
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    assert "---" in captured["query"]


def test_live_agent_name_subset_filters_to_expected_live_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.names import get_live_agent_name_subset

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    live_dir = write_orphan_meta(fake_home, "target")
    write_orphan_meta(fake_home, "done-target", done=True)
    write_orphan_meta(fake_home, "other")
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    assert get_live_agent_name_subset({"target", "done-target"}) == {
        "target": str(live_dir),
    }
