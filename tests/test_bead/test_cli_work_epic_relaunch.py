"""Successful name-reuse and relaunch tests for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_work_handler import launch_epic_bead_work
from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.bead.work import (
    EPIC_CLAN_SUMMARY_SCRIPT,
    SASE_BEAD_ID_ENV,
    SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
)

from .cli_work_helpers import (
    FakeLaunchResult,
    bead_wait_lines,
    epic_clan_declaration,
    make_args,
    seed_diamond,
    write_bead_agent_meta,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


def test_work_stale_owner_round_trip_wipes_and_rewrites(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale name registry entries are wiped, and the launcher sees a rewritten prompt."""
    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    write_bead_agent_meta(
        fake_home,
        phase_ids[0],
        bead_id=phase_ids[0],
        waiting=True,
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
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

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    query = captured["query"]
    # Launcher receives ordinary identities while retaining bead associations.
    assert "%id(!" not in query
    assert f"%id({phase_ids[0]}, bead={phase_ids[0]})\n" in query
    for pid in phase_ids[1:]:
        suffix = pid.removeprefix(f"{epic_id}.")
        assert f"%id({suffix}, clan={epic_id}, bead={pid})" in query
    assert f"%id(land, clan={epic_id}, bead={epic_id})" in query

    # Only the matching waiting owner is force-reused before launch.
    assert wiped == [phase_ids[0]]


def test_work_interrupted_phase_family_is_wiped_before_retry(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed plan and dead code member do not block deterministic retry."""
    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)
    fake_home = project_dir / "home"
    fake_home.mkdir()
    family_name = phase_ids[0]
    plan_name = f"{family_name}--plan"
    code_name = f"{family_name}--code"
    write_bead_agent_meta(
        fake_home,
        plan_name,
        bead_id=phase_ids[0],
        done=True,
        outcome="completed",
        agent_family=family_name,
        agent_family_role="plan",
    )
    write_bead_agent_meta(
        fake_home,
        code_name,
        bead_id=phase_ids[0],
        done=True,
        outcome="failed",
        agent_family=family_name,
        agent_family_role="code",
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    wiped: list[str] = []
    launched: list[str] = []

    def fake_wipe(name: str) -> AgentNameWipeResult:
        assert not launched
        wiped.append(name)
        if name in {plan_name, code_name}:
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                registry_names_removed=(name,),
            )
        return AgentNameWipeResult(target_name=name, found=False)

    monkeypatch.setattr("sase.agent.names.wipe_agent_name_for_reuse", fake_wipe)
    monkeypatch.setattr(
        "sase.agent.names.rebuild_name_registry", lambda: {"entries": {}}
    )
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda query, extra_env=None, segment_extra_env=None: (
            launched.append(query) or FakeLaunchResult()
        ),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes_to_all=True))

    assert len(launched) == 1
    assert "%id(!" not in launched[0]
    assert set(wiped) == {plan_name, code_name}


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
    monkeypatch.setattr(
        "sase.agent.names.find_agent_clan",
        lambda name: (
            type("Clan", (), {"members": (object(),)})() if name == epic_id else None
        ),
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

    assert epic_id not in wiped
    assert len(launched) == 1
    query, segment_env = launched[0]
    assert "%id(!" not in query
    assert "%clan" not in query
    assert f"#bd/work_phase_bead:{phase_ids[0]}" not in query
    for phase_id in phase_ids[1:]:
        assert f"#bd/work_phase_bead:{phase_id}" in query
        suffix = phase_id.removeprefix(f"{epic_id}.")
        assert f"%id({suffix}, clan={epic_id}, bead={phase_id})" in query
    assert f"%id(land, clan={epic_id}, bead={epic_id})" in query
    assert all(env[SASE_EPIC_CLAN_TRIBE_ENV] == "epic" for env in segment_env)
    assert segment_env[0][SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV] == EPIC_CLAN_SUMMARY_SCRIPT
    assert all(SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV not in env for env in segment_env[1:])
    assert [env[SASE_BEAD_ID_ENV] for env in segment_env] == [
        *phase_ids[1:],
        epic_id,
    ]


def test_work_preserves_running_phase_and_launches_only_missing_segments(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running phase work is omitted from prompt, preclaim, and launch metadata."""
    epic_id, phase_ids = seed_diamond(project_dir)
    preserved_phase = phase_ids[0]
    fake_home = project_dir / "home"
    fake_home.mkdir()
    write_bead_agent_meta(fake_home, preserved_phase, bead_id=preserved_phase)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    with BeadProject(project_dir) as project:
        project.update(
            preserved_phase,
            status=Status.IN_PROGRESS.value,
            assignee=preserved_phase,
        )

    captured: dict[str, Any] = {}
    original_preclaim = BeadProject.preclaim_epic_work

    def fake_preclaim(
        self: BeadProject,
        active_epic_id: str,
        phase_assignments: list[tuple[str, str]],
        land_agent_name: str | None,
    ) -> Any:
        captured["preclaim_epic"] = active_epic_id
        captured["phase_assignments"] = tuple(phase_assignments)
        captured["land_agent_name"] = land_agent_name
        return original_preclaim(
            self, active_epic_id, phase_assignments, land_agent_name
        )

    def fake_launch(
        query: str,
        *,
        segment_extra_env: tuple[dict[str, str], ...],
        expected_names: set[str],
        launch_context: Any,
    ) -> list[FakeLaunchResult]:
        captured["query"] = query
        captured["segment_extra_env"] = segment_extra_env
        captured["expected_names"] = expected_names
        captured["launch_context"] = launch_context
        return [FakeLaunchResult()]

    monkeypatch.setattr(BeadProject, "preclaim_epic_work", fake_preclaim)
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.checkpoint_epic_work_launch",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_bead_work_agents", fake_launch
    )
    monkeypatch.setattr(
        "sase.agent.names.wipe_agent_name_for_reuse",
        lambda name: pytest.fail(f"running phase must not be wiped: {name}"),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    query = captured["query"]
    assert f"#bd/work_phase_bead:{preserved_phase}" not in query
    assert f"%id({preserved_phase}, bead={preserved_phase})" not in query
    assert f"%w(bead={preserved_phase})" in query
    assert captured["phase_assignments"] == tuple(
        (phase_id, phase_id) for phase_id in phase_ids[1:]
    )
    assert captured["land_agent_name"] == f"{epic_id}.land"
    assert captured["expected_names"] == {*phase_ids[1:], f"{epic_id}.land"}
    assert [env[SASE_BEAD_ID_ENV] for env in captured["segment_extra_env"]] == [
        *phase_ids[1:],
        epic_id,
    ]
    assert (
        captured["segment_extra_env"][0][SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV]
        == EPIC_CLAN_SUMMARY_SCRIPT
    )

    with BeadProject(project_dir) as project:
        phase = project.show(preserved_phase)
        assert (phase.status, phase.assignee) == (
            Status.IN_PROGRESS,
            preserved_phase,
        )


def test_waiting_phase_that_starts_running_before_cleanup_is_preserved(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview-to-cleanup revalidation can shrink the replacement set safely."""
    epic_id, phase_ids = seed_diamond(project_dir)
    preserved_phase = phase_ids[0]
    fake_home = project_dir / "home"
    fake_home.mkdir()
    artifact_dir = write_bead_agent_meta(
        fake_home,
        preserved_phase,
        bead_id=preserved_phase,
        waiting=True,
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    captured: dict[str, Any] = {}
    original_preclaim = BeadProject.preclaim_epic_work

    def confirm_cleanup() -> bool:
        (artifact_dir / "waiting.json").unlink()
        return True

    def fake_preclaim(
        self: BeadProject,
        active_epic_id: str,
        phase_assignments: list[tuple[str, str]],
        land_agent_name: str | None,
    ) -> Any:
        captured["phase_assignments"] = tuple(phase_assignments)
        return original_preclaim(
            self, active_epic_id, phase_assignments, land_agent_name
        )

    def fake_launch(
        query: str,
        *,
        segment_extra_env: tuple[dict[str, str], ...],
        expected_names: set[str],
        launch_context: Any,
    ) -> list[FakeLaunchResult]:
        captured["query"] = query
        captured["segment_extra_env"] = segment_extra_env
        captured["expected_names"] = expected_names
        return [FakeLaunchResult()]

    monkeypatch.setattr("sase.bead.cli_work_handler.confirm_cleanup", confirm_cleanup)
    monkeypatch.setattr(BeadProject, "preclaim_epic_work", fake_preclaim)
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.checkpoint_epic_work_launch",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_bead_work_agents", fake_launch
    )
    monkeypatch.setattr(
        "sase.agent.names.wipe_agent_name_for_reuse",
        lambda name: pytest.fail(f"race-preserved phase must not be wiped: {name}"),
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert f"#bd/work_phase_bead:{preserved_phase}" not in captured["query"]
    assert captured["phase_assignments"] == tuple(
        (phase_id, phase_id) for phase_id in phase_ids[1:]
    )
    assert captured["expected_names"] == {*phase_ids[1:], f"{epic_id}.land"}


def test_work_all_running_epic_is_idempotent_without_mutation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fully preserved retry returns before readiness, preclaim, checkpoint, or spawn."""
    epic_id, phase_ids = seed_diamond(project_dir)
    land_name = f"{epic_id}.land"
    fake_home = project_dir / "home"
    fake_home.mkdir()
    for phase_id in phase_ids:
        write_bead_agent_meta(fake_home, phase_id, bead_id=phase_id)
    write_bead_agent_meta(fake_home, land_name, bead_id=epic_id)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    monkeypatch.setattr(
        BeadProject,
        "mark_ready_to_work",
        lambda *_args, **_kwargs: pytest.fail("must not mark ready"),
    )
    monkeypatch.setattr(
        BeadProject,
        "preclaim_epic_work",
        lambda *_args, **_kwargs: pytest.fail("must not preclaim"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.checkpoint_epic_work_launch",
        lambda *_args, **_kwargs: pytest.fail("must not checkpoint"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_bead_work_agents",
        lambda *_args, **_kwargs: pytest.fail("must not launch"),
    )

    with BeadProject(project_dir) as project:
        result = launch_epic_bead_work(
            project,
            epic_id,
            dry_run=False,
            yes=True,
            yes_to_all=False,
            no_push=False,
            before_agent_launch=lambda *_args: pytest.fail(
                "must not run visibility hook"
            ),
        )
        assert result.launch_state == "already_running"
        assert result.launched_agent_names == ()
        assert set(result.preserved_agent_names) == {*phase_ids, land_name}
        assert project.show(epic_id).status is Status.OPEN
        assert project.show(epic_id).is_ready_to_work is False
        assert all(
            project.show(phase_id).status is Status.OPEN for phase_id in phase_ids
        )


def test_work_all_closed_epic_launches_only_missing_lander(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A retry after every authored phase closed launches only the land agent."""
    epic_id, phase_ids = seed_diamond(project_dir)
    land_name = f"{epic_id}.land"
    with BeadProject(project_dir) as project:
        project.mark_ready_to_work(epic_id)
        for index, phase_id in enumerate(phase_ids):
            project.update(
                phase_id,
                status=Status.IN_PROGRESS.value,
                assignee=f"completed-phase-{index}",
            )
        project.close(phase_ids)
        prior_phase_state = {
            phase_id: (
                project.show(phase_id).status,
                project.show(phase_id).assignee,
                project.show(phase_id).closed_at,
            )
            for phase_id in phase_ids
        }

        captured: dict[str, Any] = {}
        original_preclaim = BeadProject.preclaim_epic_work

        def fake_preclaim(
            self: BeadProject,
            active_epic_id: str,
            phase_assignments: list[tuple[str, str]],
            land_agent_name: str | None,
        ) -> Any:
            captured["preclaim_epic"] = active_epic_id
            captured["phase_assignments"] = tuple(phase_assignments)
            captured["land_agent_name"] = land_agent_name
            return original_preclaim(
                self,
                active_epic_id,
                phase_assignments,
                land_agent_name,
            )

        def fake_launch(
            query: str,
            *,
            segment_extra_env: tuple[dict[str, str], ...],
            expected_names: set[str],
            launch_context: Any,
        ) -> list[FakeLaunchResult]:
            captured["query"] = query
            captured["segment_extra_env"] = segment_extra_env
            captured["expected_names"] = expected_names
            captured["launch_context"] = launch_context
            return [FakeLaunchResult()]

        monkeypatch.setattr(BeadProject, "preclaim_epic_work", fake_preclaim)
        monkeypatch.setattr(
            "sase.bead.cli_work_handler.checkpoint_epic_work_launch",
            lambda *_args, **_kwargs: False,
        )
        monkeypatch.setattr(
            "sase.bead.cli_work_handler.launch_bead_work_agents",
            fake_launch,
        )

        result = launch_epic_bead_work(
            project,
            epic_id,
            dry_run=False,
            yes=True,
            yes_to_all=False,
            no_push=False,
        )

        assert result.launch_state == "launched"
        assert result.launched_agent_names == (land_name,)
        assert result.preserved_agent_names == ()
        assert captured["preclaim_epic"] == epic_id
        assert captured["phase_assignments"] == ()
        assert captured["land_agent_name"] == land_name
        assert captured["expected_names"] == {land_name}
        assert len(captured["segment_extra_env"]) == 1
        assert captured["segment_extra_env"][0][SASE_BEAD_ID_ENV] == epic_id

        query = captured["query"]
        assert query.count("\n---\n") == 0
        assert "#bd/work_phase_bead" not in query
        assert f"#bd/land_epic:{epic_id}" in query
        assert f"%id({land_name}, bead={epic_id})" in query
        assert epic_clan_declaration(epic_id) in query
        assert "%w:" not in query
        assert bead_wait_lines(query) == [
            f"%w(bead={phase_id})" for phase_id in phase_ids
        ]

        epic = project.show(epic_id)
        assert (epic.status, epic.assignee) == (Status.IN_PROGRESS, land_name)
        for phase_id in phase_ids:
            phase = project.show(phase_id)
            assert (
                phase.status,
                phase.assignee,
                phase.closed_at,
            ) == prior_phase_state[phase_id]

    out = capsys.readouterr().out
    assert "0 phase agent(s) in 0 wave(s) plus 1 land agent" in out
    assert "Launched 1 agents" in out


def test_work_all_closed_epic_preserves_matching_live_lander_without_mutation(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live land-only retry is an idempotent no-op."""
    epic_id, phase_ids = seed_diamond(project_dir)
    land_name = f"{epic_id}.land"
    with BeadProject(project_dir) as project:
        for index, phase_id in enumerate(phase_ids):
            project.update(
                phase_id,
                status=Status.IN_PROGRESS.value,
                assignee=f"completed-phase-{index}",
            )
        project.close(phase_ids)
        prior_phase_state = {
            phase_id: (
                project.show(phase_id).status,
                project.show(phase_id).assignee,
                project.show(phase_id).closed_at,
            )
            for phase_id in phase_ids
        }

    fake_home = project_dir / "home"
    fake_home.mkdir()
    write_bead_agent_meta(fake_home, land_name, bead_id=epic_id)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        BeadProject,
        "mark_ready_to_work",
        lambda *_args, **_kwargs: pytest.fail("must not mark ready"),
    )
    monkeypatch.setattr(
        BeadProject,
        "preclaim_epic_work",
        lambda *_args, **_kwargs: pytest.fail("must not preclaim"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.checkpoint_epic_work_launch",
        lambda *_args, **_kwargs: pytest.fail("must not checkpoint"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.prepare_selected_bead_work_force_reuse",
        lambda *_args, **_kwargs: pytest.fail("must not clean up"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_bead_work_agents",
        lambda *_args, **_kwargs: pytest.fail("must not launch"),
    )

    with BeadProject(project_dir) as project:
        result = launch_epic_bead_work(
            project,
            epic_id,
            dry_run=False,
            yes=True,
            yes_to_all=False,
            no_push=False,
        )

        assert result.launch_state == "already_running"
        assert result.launched_agent_names == ()
        assert result.preserved_agent_names == (land_name,)
        epic = project.show(epic_id)
        assert epic.status is Status.OPEN
        assert epic.assignee == ""
        assert epic.is_ready_to_work is False
        for phase_id in phase_ids:
            phase = project.show(phase_id)
            assert (
                phase.status,
                phase.assignee,
                phase.closed_at,
            ) == prior_phase_state[phase_id]


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
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *args, **kwargs: True,
    )

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    # No phases close: this simulates the launched clan failing before it can
    # make progress, while its registered clan identity remains durable.
    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert len(launched) == 2
    declaration = epic_clan_declaration(epic_id)
    first_query, first_segment_env = launched[0]
    retry_query, retry_segment_env = launched[1]
    assert first_query.count(declaration) == 1
    assert "%clan" not in retry_query
    for phase_id in phase_ids:
        suffix = phase_id.removeprefix(f"{epic_id}.")
        assert f"%id({suffix}, clan={epic_id}, bead={phase_id})" in retry_query
    assert f"%id(land, clan={epic_id}, bead={epic_id})" in retry_query
    for segment_env in (first_segment_env, retry_segment_env):
        assert all(env[SASE_EPIC_CLAN_TRIBE_ENV] == "epic" for env in segment_env)
        assert (
            segment_env[0][SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV]
            == EPIC_CLAN_SUMMARY_SCRIPT
        )
        assert all(
            SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV not in env for env in segment_env[1:]
        )
