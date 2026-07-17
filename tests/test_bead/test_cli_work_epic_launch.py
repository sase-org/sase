"""Launch and rendering tests for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.bead.work import (
    SASE_BEAD_ID_ENV,
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_PLAN_REF_ENV,
    SASE_PHASE_BEAD_ID_ENV,
)

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
    family_directive = f"%family({epic_id}, role=phase)"
    assert query.count(family_directive) == len(phase_ids)
    assert "%group:" not in query
    for pid in phase_ids:
        assert f"#bd/work_phase_bead:{pid}" in query
        assert f"%name:{pid}\n{family_directive}" in query
    land_segment = query.split("\n---\n")[-1]
    assert family_directive not in land_segment
    assert f"#bd/land_epic:{epic_id}" in query
    assert captured["extra_env"] is None
    assert captured["segment_extra_env"] == tuple(
        [
            {
                SASE_BEAD_ID_ENV: phase_id,
                SASE_EPIC_BEAD_ID_ENV: epic_id,
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
                SASE_EPIC_PLAN_REF_ENV: plan_ref,
                INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
            }
        ]
    )
    assert commit_calls == [
        (project_dir / "sdd/beads", epic_id, "Diamond epic", "epic")
    ]

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


def test_work_stale_owner_round_trip_wipes_and_rewrites(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale name registry entries are wiped, and the launcher sees a rewritten prompt."""
    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)
    captured: dict[str, Any] = {}
    wiped: list[str] = []

    def fake_wipe(name: str) -> AgentNameWipeResult:
        # Force-reuse preparation must complete before the launcher runs.
        assert "query" not in captured
        wiped.append(name)
        return AgentNameWipeResult(target_name=name, found=False)

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        captured["query"] = query
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    query = captured["query"]
    # Launcher receives the rewritten prompt: ordinary %name:<n> (no '!').
    assert "%name:!" not in query
    for pid in phase_ids:
        assert f"%name:{pid}\n" in query
    assert f"%name:{epic_id}\n" in query

    # Every planned phase and land name is force-reused before launch, plus the
    # legacy ``<epic_id>.land`` owner the new prompt no longer names.
    assert set(wiped) == {*phase_ids, epic_id, f"{epic_id}.land"}


@pytest.mark.parametrize(
    "failure_mode",
    [
        pytest.param("raise", id="wipe-raises"),
        pytest.param("errors", id="wipe-reports-errors"),
        pytest.param("residual", id="name-still-reserved"),
    ],
)
def test_work_force_reuse_cleanup_failure_aborts_before_mutation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_mode: str,
) -> None:
    """A failed forced-reuse wipe aborts before any bead mutation or launch."""
    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)

    def fake_wipe(name: str) -> AgentNameWipeResult:
        if failure_mode == "raise":
            raise RuntimeError("kaboom")
        if failure_mode == "errors":
            return AgentNameWipeResult(target_name=name, found=True, errors=("kaboom",))
        # residual: found but never removed from the registry.
        return AgentNameWipeResult(
            target_name=name, found=True, registry_names_removed=()
        )

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)

    launched: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: pytest.fail("aborted launch must not commit"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "forced reuse cleanup" in err
    assert launched == []
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


def test_work_dry_run_never_mutates_or_launches(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    launch_calls: list[str] = []

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        launch_calls.append(query)
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: pytest.fail("dry run must not commit"),
    )

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
    assert out.count(f"%family({epic_id}, role=phase)") == len(phase_ids)
    assert "%group:" not in out


def test_work_dry_run_renders_model_directives(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Models epic", IssueType.PLAN, model="claude/opus")
        p1 = proj.create(
            "P1",
            IssueType.PHASE,
            parent_id=epic.id,
            model="codex/gpt-5.6-sol",
        )
        p2 = proj.create("P2", IssueType.PHASE, parent_id=epic.id)
    epic_id, p1_id, p2_id = epic.id, p1.id, p2.id

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: FakeLaunchResult(),
    )

    bead_cli.handle_bead_work(make_args(epic_id, dry_run=True, yes=True))

    out = capsys.readouterr().out
    family_directive = f"%family({epic_id}, role=phase)"
    assert (
        f"%name:!{p1_id}\n{family_directive}\n"
        "%model:codex/gpt-5.6-sol\n%auto:tale" in out
    )
    # Phase without an explicit model defaults to the phase-worker role alias.
    assert (
        f"%name:!{p2_id}\n{family_directive}\n%model:@phase_worker\n%auto:tale" in out
    )
    # The epic's explicit land model still wins over the epic-lander alias.
    assert f"%name:!{epic_id}\n%model:claude/opus\n%auto:tale" in out
    assert out.count(family_directive) == 2
    assert "%group:" not in out
    # Three %model directives: explicit phase, phase-worker phase, and land.
    assert out.count("%model:") == 3
    assert out.count("%auto:tale") == 3


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
    family_directive = f"%family({epic_id}, role=phase)"
    for pid in phase_ids:
        assert f"#git:sase\n%name:!{pid}\n{family_directive}" in out
        assert f"#bd/work_phase_bead:{pid}" in out
    assert f"#git:sase\n%name:!{epic_id}\n%model:@epic_lander" in out
    assert f"#bd/land_epic:{epic_id}" in out
    assert out.count(family_directive) == len(phase_ids)
    assert "%group:" not in out

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
    family_directive = f"%family({epic_id}, role=phase)"
    assert "#git:sase #pr(name=feature_epic, bug_id=12345)" in out
    assert (
        f"#git:sase #pr(name=feature_epic, bug_id=12345)\n"
        f"%name:!{phase_ids[0]}\n{family_directive}" in out
    )
    assert f"#git:feature_epic\n%name:!{phase_ids[1]}\n{family_directive}" in out
    assert f"#git:feature_epic\n%name:!{epic_id}\n%model:@epic_lander" in out
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in out
    assert f"#bd/land_epic:{epic_id}" in out
    assert out.count(family_directive) == len(phase_ids)
    assert "%group:" not in out

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""
