"""Successful name-reuse and relaunch tests for epic ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.project import BeadProject
from sase.bead.work import (
    EPIC_CLAN_SUMMARY_SCRIPT,
    SASE_BEAD_ID_ENV,
    SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
)

from .cli_work_helpers import (
    FakeLaunchResult,
    epic_clan_declaration,
    make_args,
    seed_diamond,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")


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


def test_work_interrupted_phase_family_is_wiped_before_retry(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed plan and dead code member do not block deterministic retry."""
    from types import SimpleNamespace

    from sase.agent.names import AgentNameWipeResult

    epic_id, phase_ids = seed_diamond(project_dir)
    family_name = phase_ids[0]
    plan_name = f"{family_name}--plan"
    code_name = f"{family_name}--code"
    wiped: list[str] = []
    launched: list[str] = []

    monkeypatch.setattr(
        "sase.agent.names.find_agent_family",
        lambda name: (
            SimpleNamespace(
                members=(
                    SimpleNamespace(name=plan_name, outcome="completed"),
                    SimpleNamespace(name=code_name, outcome=None),
                )
            )
            if name == family_name
            else None
        ),
    )

    def fake_wipe(name: str) -> AgentNameWipeResult:
        assert not launched
        wiped.append(name)
        if name == family_name:
            return AgentNameWipeResult(
                target_name=name,
                found=True,
                skipped_container_kind="family",
            )
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

    bead_cli.handle_bead_work(make_args(epic_id, yes=True))

    assert len(launched) == 1
    assert "%id(!" not in launched[0]
    assert wiped[:3] == [family_name, code_name, plan_name]
    assert set(wiped) == {
        *phase_ids,
        epic_id,
        f"{epic_id}.land",
        plan_name,
        code_name,
    }


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
    assert segment_env[0][SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV] == EPIC_CLAN_SUMMARY_SCRIPT
    assert all(SASE_EPIC_CLAN_SUMMARY_SCRIPT_ENV not in env for env in segment_env[1:])
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
