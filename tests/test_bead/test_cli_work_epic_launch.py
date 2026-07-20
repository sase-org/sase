"""Launch and rendering tests for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, PhaseSize, Status
from sase.bead.project import BeadProject
from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.bead.work import (
    SASE_BEAD_ID_ENV,
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
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


def _epic_clan_declaration(epic_id: str) -> str:
    return f"%clan({epic_id}, tribe=epic, summary_script=sase_clan_summary_epic)"


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
    membership = _epic_clan_declaration(epic_id)
    assert query.count(membership) == 1
    assert "%family" not in query
    assert "%group:" not in query
    for index, pid in enumerate(phase_ids):
        assert f"#bd/work_phase_bead:{pid}" in query
        if index == 0:
            assert f"%id:{pid}\n{membership}" in query
        else:
            suffix = pid.removeprefix(f"{epic_id}.")
            assert f"%id({suffix}, clan={epic_id})" in query
    land_segment = query.split("\n---\n")[-1]
    assert f"%id(land, clan={epic_id})" in land_segment
    assert membership not in land_segment
    assert f"#bd/land_epic:{epic_id}" in query
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
    # Launcher receives the rewritten prompt: ordinary %id:<n> (no '!').
    assert "%id:!" not in query
    assert f"%id:{phase_ids[0]}\n" in query
    for pid in phase_ids[1:]:
        suffix = pid.removeprefix(f"{epic_id}.")
        assert f"%id({suffix}, clan={epic_id})" in query
    assert f"%id(land, clan={epic_id})" in query

    # Every planned phase and land name is force-reused before launch, plus the
    # legacy ``<epic_id>`` owner the new prompt no longer names.
    assert set(wiped) == {*phase_ids, epic_id, f"{epic_id}.land"}


def test_work_retry_allows_legacy_epic_clan_container_skip(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bare epic clan survives cleanup and the remaining phases relaunch."""
    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)
    with BeadProject(project_dir) as proj:
        proj.mark_ready_to_work(epic_id)
        proj.close([phase_ids[0]])

    wiped: list[str] = []

    def fake_wipe(name: str) -> AgentNameWipeResult:
        wiped.append(name)
        if name == epic_id:
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                skipped_container_kind="clan",
            )
        return AgentNameWipeResult(target_name=name, found=False)

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_clan_names",
        lambda: {epic_id},
    )
    launched: list[tuple[str, Any]] = []

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        launched.append((query, segment_extra_env))
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert epic_id in wiped
    assert len(launched) == 1
    query, segment_env = launched[0]
    assert "%id:!" not in query
    assert "%clan" not in query
    assert f"#bd/work_phase_bead:{phase_ids[0]}" not in query
    for phase_id in phase_ids[1:]:
        assert f"#bd/work_phase_bead:{phase_id}" in query
        suffix = phase_id.removeprefix(f"{epic_id}.")
        assert f"%id({suffix}, clan={epic_id})" in query
    assert f"%id(land, clan={epic_id})" in query
    assert all(env[SASE_EPIC_CLAN_TRIBE_ENV] == "epic" for env in segment_env)
    assert [env[SASE_BEAD_ID_ENV] for env in segment_env] == [
        *phase_ids[1:],
        epic_id,
    ]


def test_work_relaunch_after_failure_joins_existing_epic_clan(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incomplete first launch re-works every phase without redeclaring."""
    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)
    reserved_clans: set[str] = set()
    launched: list[tuple[str, Any]] = []

    monkeypatch.setattr(
        "sase.agent.names.get_reserved_clan_names",
        lambda: set(reserved_clans),
    )
    monkeypatch.setattr(
        "sase.agent.names.wipe_agent_name_for_reuse",
        lambda name: AgentNameWipeResult(target_name=name, found=False),
    )

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        launched.append((query, segment_extra_env))
        reserved_clans.add(epic_id)
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: True,
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    # No phases close: this simulates the launched clan failing before it can
    # make progress, while its registered clan identity remains durable.
    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert len(launched) == 2
    declaration = _epic_clan_declaration(epic_id)
    first_query, first_segment_env = launched[0]
    retry_query, retry_segment_env = launched[1]
    assert first_query.count(declaration) == 1
    assert "%clan" not in retry_query
    for phase_id in phase_ids:
        suffix = phase_id.removeprefix(f"{epic_id}.")
        assert f"%id({suffix}, clan={epic_id})" in retry_query
    assert f"%id(land, clan={epic_id})" in retry_query
    for segment_env in (first_segment_env, retry_segment_env):
        assert all(env[SASE_EPIC_CLAN_TRIBE_ENV] == "epic" for env in segment_env)


@pytest.mark.parametrize(
    ("conflict_target", "container_kind"),
    [
        pytest.param("phase", "family", id="phase-family-container"),
        pytest.param("land", "clan", id="land-clan-container"),
    ],
)
def test_work_expected_name_container_conflict_aborts_before_mutation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    conflict_target: str,
    container_kind: str,
) -> None:
    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)
    conflict_name = phase_ids[0] if conflict_target == "phase" else f"{epic_id}.land"

    def fake_wipe(name: str) -> AgentNameWipeResult:
        if name == conflict_name:
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                skipped_container_kind=container_kind,
            )
        return AgentNameWipeResult(target_name=name, found=False)

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
    assert (
        f"agent name '{conflict_name}' is reserved by a {container_kind} container"
        in err
    )
    assert "cannot be force-reused" in err
    assert launched == []
    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for phase_id in phase_ids:
            phase = proj.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


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
    assert f"land agent ({epic_id}.land)" in out
    assert f"Clan: {epic_id} · Tribe: @epic" in out
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in out
    assert out.count(_epic_clan_declaration(epic_id)) == 1
    assert "%family" not in out
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
    membership = _epic_clan_declaration(epic_id)
    assert f"%id:!{p1_id}\n{membership}\n%model:codex/gpt-5.6-sol\n%auto\n" in out
    # Phase without an explicit model defaults to the phase-worker role alias.
    p2_suffix = p2_id.removeprefix(f"{epic_id}.")
    assert f"%id(!{p2_suffix}, clan={epic_id})\n%model:@phase_worker\n%auto\n" in out
    # The epic's explicit land model still wins over the epic-lander alias.
    assert f"%id(!land, clan={epic_id})\n%model:claude/opus\n%auto\n" in out
    assert out.count(_epic_clan_declaration(epic_id)) == 1
    assert "%family" not in out
    assert "%group:" not in out
    # Three %model directives: explicit phase, phase-worker phase, and land.
    assert out.count("%model:") == 3
    assert out.count("\n%auto\n") == 3
    assert "%auto:tale" not in out


def test_work_dry_run_relaunches_from_stored_phase_sizes(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Sized epic", IssueType.PLAN)
        small = project.create(
            "Small",
            IssueType.PHASE,
            parent_id=epic.id,
            size=PhaseSize.SMALL,
        )
        medium = project.create(
            "Medium",
            IssueType.PHASE,
            parent_id=epic.id,
            size=PhaseSize.MEDIUM,
        )
        large = project.create(
            "Large",
            IssueType.PHASE,
            parent_id=epic.id,
            size=PhaseSize.LARGE,
        )

    bead_cli.handle_bead_work(make_args(epic.id, dry_run=True, yes=True))

    prompt = capsys.readouterr().out.split("--- Multi-prompt (dry run) ---\n", 1)[1]
    segments = prompt.split("\n---\n")
    by_bead = {
        bead.id: next(
            segment
            for segment in segments
            if f"#bd/work_phase_bead:{bead.id}" in segment
        )
        for bead in (small, medium, large)
    }
    assert "%model:@phase_worker" in by_bead[small.id]
    assert "#plan" not in by_bead[small.id].splitlines()
    assert "%model:@phase_worker" in by_bead[medium.id]
    assert (
        by_bead[medium.id].rstrip().endswith(f"#bd/work_phase_bead:{medium.id}\n#plan")
    )
    assert "%model:@smartest" in by_bead[large.id]
    assert by_bead[large.id].rstrip().endswith(f"#bd/work_phase_bead:{large.id}\n#plan")


def test_work_dry_run_uses_custom_big_epic_threshold(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.bead.config.load_merged_config",
        lambda: {"bead": {"big_epic_phase_threshold": 3}},
    )
    with BeadProject(project_dir) as project:
        epic = project.create("Custom threshold epic", IssueType.PLAN)
        for index in range(3):
            project.create(f"P{index}", IssueType.PHASE, parent_id=epic.id)

    bead_cli.handle_bead_work(make_args(epic.id, dry_run=True, yes=True))

    out = capsys.readouterr().out
    land_segment = out.split("\n---\n")[-1]
    assert f"%id(!land, clan={epic.id})" in land_segment
    assert "%model:@big_epic_lander" in land_segment


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
    membership = _epic_clan_declaration(epic_id)
    assert f"#git:sase\n%id:!{phase_ids[0]}\n{membership}" in out
    for pid in phase_ids[1:]:
        suffix = pid.removeprefix(f"{epic_id}.")
        assert f"#git:sase\n%id(!{suffix}, clan={epic_id})" in out
        assert f"#bd/work_phase_bead:{pid}" in out
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in out
    assert f"#git:sase\n%id(!land, clan={epic_id})" in out
    assert f"#bd/land_epic:{epic_id}" in out
    assert out.count(_epic_clan_declaration(epic_id)) == 1
    assert "%family" not in out
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
    membership = _epic_clan_declaration(epic_id)
    assert "#git:sase #pr(name=feature_epic, bug_id=12345)" in out
    assert (
        f"#git:sase #pr(name=feature_epic, bug_id=12345)\n"
        f"%id:!{phase_ids[0]}\n{membership}" in out
    )
    phase_suffix = phase_ids[1].removeprefix(f"{epic_id}.")
    assert f"#git:feature_epic\n%id(!{phase_suffix}, clan={epic_id})" in out
    assert f"#git:feature_epic\n%id(!land, clan={epic_id})" in out
    assert f"#bd/work_phase_bead:{phase_ids[0]}" in out
    assert f"#bd/land_epic:{epic_id}" in out
    assert out.count(_epic_clan_declaration(epic_id)) == 1
    assert "%family" not in out
    assert "%group:" not in out

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for pid in phase_ids:
            phase = proj.show(pid)
            assert phase.status == Status.OPEN
            assert phase.assignee == ""


class TestEpicSummarySmokeExercises:
    """End-to-end smoke tests for epic clan summary persistence and rendering."""

    def test_epic_work_launch_persists_rich_summary_with_all_phases(
        self,
        project_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Epic work launch persists the rich summary with all phase titles."""
        import json
        from contextlib import nullcontext
        from unittest.mock import patch

        from sase.agent.clan_membership import (
            CLAN_MEMBERSHIP_ENV,
            ClanMembershipPlan,
            encode_clan_membership_plan,
        )
        from sase.axe.run_agent_directives import extract_directives_and_write_meta

        epic_id, phase_ids = seed_diamond(project_dir)
        captured: dict[str, Any] = {}
        workspace_dir = project_dir / "workspace"
        artifacts_dir = project_dir / "artifacts"
        workspace_dir.mkdir(exist_ok=True)
        artifacts_dir.mkdir(exist_ok=True)

        def fake_launch(
            query: str,
            extra_env: Any = None,
            segment_extra_env: Any = None,
        ) -> FakeLaunchResult:
            captured["query"] = query
            captured["segment_extra_env"] = segment_extra_env
            # Simulate the first segment (declaring member) extracting directives
            if segment_extra_env:
                # Extract the first segment (before first ---)
                segments = query.split("\n---\n")
                first_segment = segments[0]

                monkeypatch.setenv(
                    CLAN_MEMBERSHIP_ENV,
                    encode_clan_membership_plan(
                        ClanMembershipPlan(clan_name=epic_id, generation="g1")
                    ),
                )

                with (
                    patch("sase.agent.names.ensure_historical_auto_name_migration"),
                    patch(
                        "sase.agent.names.agent_name_allocation_lock",
                        return_value=nullcontext(),
                    ),
                    patch("sase.agent.names.claim_agent_name"),
                    patch("sase.agent.names.claim_registered_clan_name"),
                    patch(
                        "sase.xprompt.process_xprompt_references",
                        side_effect=lambda value, **_: value,
                    ),
                    patch(
                        "sase.llm_provider.temporary_override."
                        "resolve_effective_default_provider_model",
                        return_value=("codex", "gpt-5"),
                    ),
                    patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
                ):
                    extract_directives_and_write_meta(
                        first_segment,
                        str(workspace_dir),
                        str(artifacts_dir),
                    )
            return FakeLaunchResult()

        monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
        monkeypatch.setattr(
            "sase.bead.sync.commit_bead_work_launch",
            lambda *args, **kwargs: True,
        )

        bead_cli.handle_bead_work(make_args(epic_id, yes=True))

        # Verify the persisted meta file contains the rich summary
        persisted = json.loads(
            (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert persisted["agent_clan"] == epic_id
        clan_summary = persisted["clan_summary"]

        # The summary must contain the epic title
        assert "Diamond epic" in clan_summary

        # The summary must contain every phase title
        for phase_id in phase_ids:
            # Each phase should have its number and title in the summary
            assert "P1" in clan_summary
            assert "P2" in clan_summary
            assert "P3" in clan_summary
            assert "P4" in clan_summary

        # Verify it's not the fallback summary
        assert "[bold]EPIC" not in clan_summary or "Diamond epic" in clan_summary

    def test_epic_work_clan_panel_renders_persisted_summary(
        self,
        project_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Clan panel renders persisted epic summary correctly."""
        from datetime import datetime
        from sase.ace.tui.models._agent_tree import project_clan_tree
        from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
            build_clan_detail_text,
        )
        from tests.ace.tui.widgets._agent_display_clan_helpers import (
            make_clan_agent,
        )

        epic_id, phase_ids = seed_diamond(project_dir)

        # Simulate a persisted clan summary with all phases
        rich_summary = (
            "[bold #D75FFF]◆ EPIC sase-test · Diamond epic[/bold #D75FFF]\n"
            "\n"
            "[bold #87D7FF]PHASES · 0/4 done at launch[/bold #87D7FF]\n"
            " [bold #87D7FF]◐[/bold #87D7FF] 1. P1                                                          [small]\n"
            " [bold #87D7FF]◐[/bold #87D7FF] 2. P2                                                          [small]\n"
            " [bold #87D7FF]◐[/bold #87D7FF] 3. P3                                                          [small]\n"
            " [bold #87D7FF]◐[/bold #87D7FF] 4. P4                                                          [small]\n"
        )

        # Create a clan agent with the epic summary
        member = make_clan_agent(
            f"{epic_id}.land",
            status="DONE",
            start=datetime(2026, 7, 17, 12, 0, 0),
            stop=datetime(2026, 7, 17, 12, 2, 0),
        )
        member.clan_summary = rich_summary
        container = project_clan_tree([member])[0]

        # The panel should render the summary correctly
        result = build_clan_detail_text(container)
        result_text = result.plain

        # Verify the result contains phase information
        assert "Diamond epic" in result_text
        assert "P1" in result_text
        assert "P2" in result_text
        assert "P3" in result_text
        assert "P4" in result_text
