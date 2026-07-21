"""Confirmed launch contract tests for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_work_handler import BeadWorkError, launch_epic_bead_work
from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.bead.work import (
    SASE_BEAD_ID_ENV,
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
    SASE_EPIC_PLAN_REF_ENV,
    SASE_EPIC_PLAN_SNAPSHOT_ENV,
    SASE_PHASE_BEAD_ID_ENV,
)
from sase.xprompt.directives import extract_prompt_directives

from .cli_work_helpers import (
    FakeLaunchResult,
    bead_wait_lines,
    epic_clan_declaration,
    make_args,
    seed_diamond,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_prelaunch_visibility_failure_never_reaches_agent_launcher(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, _phase_ids = seed_diamond(project_dir)
    launcher_reached = False
    barrier_observations: list[bool] = []

    def unexpected_launch(*_args: object, **_kwargs: object) -> object:
        nonlocal launcher_reached
        launcher_reached = True
        raise AssertionError("agent launcher crossed a failed visibility barrier")

    def fail_visibility(project: BeadProject, active_epic_id: str) -> None:
        barrier_observations.append(project.show(active_epic_id).is_ready_to_work)
        raise BeadWorkError(
            "graph publication failed",
            preserve_epic_state=True,
        )

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_bead_work_agents",
        unexpected_launch,
    )

    with BeadProject(project_dir) as project:
        with pytest.raises(BeadWorkError, match="graph publication failed") as excinfo:
            launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=True,
                no_push=False,
                before_agent_launch=fail_visibility,
            )
        assert excinfo.value.agents_spawned is False
        assert project.show(epic_id).is_ready_to_work is True

    assert barrier_observations == [True]
    assert launcher_reached is False


def test_work_launches_and_passes_rendered_multi_prompt(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    plan_ref = "sdd/plans/202607/diamond.md"
    with BeadProject(project_dir) as project:
        project.update(epic_id, design=plan_ref)
    captured: dict[str, Any] = {}
    commit_calls: list[tuple[Path, str, str, str]] = []

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        captured["query"] = query
        captured["extra_env"] = extra_env
        captured["segment_extra_env"] = segment_extra_env
        return FakeLaunchResult()

    def fake_commit(
        beads_dir: Path,
        bead_id: str,
        title: str,
        *,
        kind: str,
    ) -> bool:
        commit_calls.append((beads_dir, bead_id, title, kind))
        return True

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
    monkeypatch.setattr("sase.bead.sync.commit_bead_work_launch", fake_commit)

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    # Launcher was called exactly once with a multi-prompt referencing every phase.
    query = captured["query"]
    assert "---" in query
    membership = epic_clan_declaration(epic_id)
    assert query.count(membership) == 1
    assert "%family" not in query
    assert "%group:" not in query
    for index, pid in enumerate(phase_ids):
        assert f"#bd/work_phase_bead:{pid}" in query
        if index == 0:
            assert f"%id({pid}, bead={pid})\n{membership}" in query
        else:
            suffix = pid.removeprefix(f"{epic_id}.")
            assert f"%id({suffix}, clan={epic_id}, bead={pid})" in query
    land_segment = query.split("\n---\n")[-1]
    assert f"%id(land, clan={epic_id}, bead={epic_id})" in land_segment
    assert membership not in land_segment
    assert f"#bd/land_epic:{epic_id}" in query
    assert bead_wait_lines(land_segment) == [
        f"%w(bead={phase_id})" for phase_id in phase_ids
    ]
    assert captured["extra_env"] is None
    assert captured["segment_extra_env"] == tuple(
        [
            {
                SASE_BEAD_ID_ENV: phase_id,
                SASE_EPIC_BEAD_ID_ENV: epic_id,
                SASE_EPIC_CLAN_TRIBE_ENV: "epic",
                SASE_EPIC_PLAN_REF_ENV: plan_ref,
                SASE_PHASE_BEAD_ID_ENV: phase_id,
                INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
            }
            for phase_id in phase_ids
        ]
        + [
            {
                SASE_BEAD_ID_ENV: epic_id,
                SASE_EPIC_BEAD_ID_ENV: epic_id,
                SASE_EPIC_CLAN_TRIBE_ENV: "epic",
                SASE_EPIC_PLAN_REF_ENV: plan_ref,
                INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
            }
        ]
    )
    for segment, env in zip(
        query.split("\n---\n"), captured["segment_extra_env"], strict=True
    ):
        _, directives = extract_prompt_directives(segment)
        assert directives.bead_id == env[SASE_BEAD_ID_ENV]
    assert commit_calls == [
        (project_dir / "sdd/beads", epic_id, "Diamond epic", "epic")
    ]

    # Launch approval owns readiness; mocked runners have not claimed anything.
    with BeadProject(project_dir) as proj:
        epic = proj.show(epic_id)
        assert epic.is_ready_to_work is True
        assert epic.status == Status.OPEN
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""

    out = capsys.readouterr().out
    assert "Launched" in out


def test_launch_snapshots_authoritative_plan_and_overwrites_on_relaunch(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, _phase_ids = seed_diamond(project_dir)
    plan_ref = "sdd/plans/202607/diamond.md"
    source = project_dir / plan_ref
    source.parent.mkdir(parents=True)
    source.write_text("approved plan v1", encoding="utf-8")
    with BeadProject(project_dir) as project:
        project.update(epic_id, design=plan_ref)

    state_home = project_dir / "state"
    monkeypatch.setenv("SASE_HOME", str(state_home))
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda: "project",
    )
    launched_envs: list[tuple[dict[str, str], ...]] = []

    def fake_launch(
        _query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        del extra_env
        launched_envs.append(segment_extra_env)
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: True,
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    snapshot = (
        state_home / "projects/project/artifacts/epic-plans" / f"{epic_id}.md"
    ).resolve()
    assert snapshot.read_text(encoding="utf-8") == "approved plan v1"
    assert all(
        env[SASE_EPIC_PLAN_SNAPSHOT_ENV] == str(snapshot) for env in launched_envs[-1]
    )

    source.write_text("approved plan v2", encoding="utf-8")
    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert snapshot.read_text(encoding="utf-8") == "approved plan v2"
    assert all(
        env[SASE_EPIC_PLAN_SNAPSHOT_ENV] == str(snapshot) for env in launched_envs[-1]
    )


def test_dry_run_does_not_snapshot_epic_plan(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic_id, _phase_ids = seed_diamond(project_dir)
    with BeadProject(project_dir) as project:
        project.update(epic_id, design="sdd/plans/202607/diamond.md")
    monkeypatch.setattr(
        "sase.bead.cli_work_handler._snapshot_epic_plan",
        lambda *args, **kwargs: pytest.fail("dry run attempted to write a snapshot"),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True))


def test_snapshot_failure_warns_and_launches_without_snapshot_metadata(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, _phase_ids = seed_diamond(project_dir)
    plan_ref = "sdd/plans/202607/diamond.md"
    source = project_dir / plan_ref
    source.parent.mkdir(parents=True)
    source.write_text("private approved plan contents", encoding="utf-8")
    with BeadProject(project_dir) as project:
        project.update(epic_id, design=plan_ref)
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda: "project",
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler._atomic_copy_epic_plan",
        lambda *_args: (_ for _ in ()).throw(PermissionError("snapshot denied")),
    )
    launched: dict[str, Any] = {}

    def fake_launch(
        _query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        del extra_env
        launched["envs"] = segment_extra_env
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: True,
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert all(SASE_EPIC_PLAN_SNAPSHOT_ENV not in env for env in launched["envs"])
    warning = capsys.readouterr().err
    assert "could not snapshot approved plan" in warning
    assert plan_ref in warning
    assert "project" in warning
    assert "PermissionError" in warning
    assert "private approved plan contents" not in warning


@pytest.mark.parametrize(
    ("layout", "plan_ref", "source_relative"),
    [
        (
            "local",
            ".sase/sdd/plans/202607/epic.md",
            "plans/202607/epic.md",
        ),
        (
            "sidecar",
            "sase/repos/plans/202607/epic.md",
            "202607/epic.md",
        ),
    ],
)
def test_snapshot_source_resolution_uses_non_vc_bead_store_root(
    tmp_path: Path,
    layout: str,
    plan_ref: str,
    source_relative: str,
) -> None:
    from sase.bead.cli_work_handler import _epic_plan_source_path

    root = tmp_path / (".sase/sdd" if layout == "local" else "plans-sidecar")
    with BeadProject.init(root, beads_dirname="beads"):
        pass
    source = root / source_relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("approved", encoding="utf-8")

    with BeadProject(root, beads_dirname="beads") as project:
        assert _epic_plan_source_path(project, plan_ref) == source.resolve()
