"""VCS wrapper rendering tests for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Status
from sase.bead.project import BeadProject

from .cli_work_helpers import (
    FakeLaunchResult,
    bead_wait_lines,
    epic_clan_declaration,
    make_args,
    seed_patch_epic,
    seed_diamond,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


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
    (project_root / "sase.sase").write_text(
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
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    assert launch_calls == []
    out = capsys.readouterr().out
    membership = epic_clan_declaration(epic_id)
    assert f"#git:sase\n%id(!{phase_ids[0]}, bead={phase_ids[0]})\n{membership}" in out
    for pid in phase_ids[1:]:
        suffix = pid.removeprefix(f"{epic_id}.")
        assert f"#git:sase\n%id(!{suffix}, clan={epic_id}, bead={pid})" in out
        assert f"#bd/work_phase_bead:{pid}" in out
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in out
    assert f"#git:sase\n%id(!land, clan={epic_id}, bead={epic_id})" in out
    assert f"#bd/land_epic:{epic_id}" in out
    assert out.count(epic_clan_declaration(epic_id)) == 1
    assert "%family" not in out
    assert "%group:" not in out
    assert bead_wait_lines(out) == [
        f"%w(bead={phase_ids[0]})",
        f"%w(bead={phase_ids[0]})",
        f"%w(bead={phase_ids[1]})",
        f"%w(bead={phase_ids[2]})",
        *[f"%w(bead={phase_id})" for phase_id in phase_ids],
    ]

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


def test_work_dry_run_renders_patch_launch_wrappers(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_patch_epic(project_dir)
    fake_home = tmp_path / "home"
    project_root = fake_home / ".sase" / "projects" / "sase"
    project_root.mkdir(parents=True)
    (project_root / "sase.sase").write_text(
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
        lambda query, extra_env=None, segment_extra_env=None: (
            launch_calls.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    assert launch_calls == []
    out = capsys.readouterr().out
    membership = epic_clan_declaration(epic_id)
    assert "#git:sase #pr(name=feature_epic, bug_id=12345)" in out
    assert (
        f"#git:sase #pr(name=feature_epic, bug_id=12345)\n"
        f"%id(!{phase_ids[0]}, bead={phase_ids[0]})\n{membership}" in out
    )
    phase_suffix = phase_ids[1].removeprefix(f"{epic_id}.")
    assert (
        f"#git:feature_epic\n"
        f"%id(!{phase_suffix}, clan={epic_id}, bead={phase_ids[1]})" in out
    )
    assert f"#git:feature_epic\n%id(!land, clan={epic_id}, bead={epic_id})" in out
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in out
    assert f"#bd/land_epic:{epic_id}" in out
    assert out.count(epic_clan_declaration(epic_id)) == 1
    assert "%family" not in out
    assert "%group:" not in out
    assert bead_wait_lines(out) == [
        f"%w(bead={phase_ids[0]})",
        f"%w(bead={phase_ids[0]})",
        f"%w(bead={phase_ids[1]})",
    ]

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""
