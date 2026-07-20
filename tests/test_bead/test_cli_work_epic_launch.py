"""Confirmed launch and name-reuse tests for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.bead.work import (
    SASE_BEAD_ID_ENV,
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
    SASE_EPIC_PLAN_REF_ENV,
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
    # Launcher receives ordinary identities while retaining bead associations.
    assert "%id(!" not in query
    assert f"%id({phase_ids[0]}, bead={phase_ids[0]})\n" in query
    for pid in phase_ids[1:]:
        suffix = pid.removeprefix(f"{epic_id}.")
        assert f"%id({suffix}, clan={epic_id}, bead={pid})" in query
    assert f"%id(land, clan={epic_id}, bead={epic_id})" in query

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
    assert "%id(!" not in query
    assert "%clan" not in query
    assert f"#bd/work_phase_bead:{phase_ids[0]}" not in query
    for phase_id in phase_ids[1:]:
        assert f"#bd/work_phase_bead:{phase_id}" in query
        suffix = phase_id.removeprefix(f"{epic_id}.")
        assert f"%id({suffix}, clan={epic_id}, bead={phase_id})" in query
    assert f"%id(land, clan={epic_id}, bead={epic_id})" in query
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
