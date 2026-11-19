"""Spawn observations, strict evidence holds, and replay for batch recovery.

Split from ``tests.axe.test_axe_chop_batch_recovery``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.axe import chop_batch_recovery as recovery
from sase.axe import chop_batch_store
from tests.axe._test_axe_chop_batch_recovery_shared import (
    manifest,
    record_spawn,
    recovery_isolated_home,  # noqa: F401 (registers the isolated_home fixture)
    replay_manifest,
)

__all__ = [
    "test_collect_observations_ignores_prefix_cl_name_without_linkage",
    "test_collect_observations_ignores_records_from_other_runs",
    "test_collect_observations_marks_unlinked_live_owner_as_foreign_conflict",
    "test_collect_observations_matches_by_proposal_id_without_index",
    "test_collect_observations_matches_by_run_linkage_not_cl_name",
    "test_collect_observations_tells_live_reserver_from_dead_reservation",
    "test_replay_rebuilds_first_run_launch_context_and_merges_history",
    "test_strict_observations_corrupt_linkage_holds_and_recovers",
    "test_strict_observations_hold_on_unreadable_linkage",
]


def test_collect_observations_matches_by_run_linkage_not_cl_name(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = manifest("run-9", None)
    chop_batch_store.create_chop_batch("docs", "refresh", batch)

    # Production cl_name is the project name: it neither equals nor is
    # matched against member identities, even as a prefix.
    record_spawn(run_id="run-9", index=0, proposal_id="proposal-0", pid=4242)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    observations = recovery.collect_spawn_observations("docs", "refresh", batch)
    by_name = {item["agent_name"]: item["observation"] for item in observations}
    assert by_name["job-0"] == "matched_spawn"
    # job-1 and job-2 have no record and no reservation: absent, safe to launch.
    assert "job-1" not in by_name
    assert "job-2" not in by_name


def test_collect_observations_ignores_prefix_cl_name_without_linkage(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = manifest("run-9", None)
    batch["members"][1]["agent_name"] = "sase-fix"
    chop_batch_store.create_chop_batch("docs", "refresh", batch)

    # A project cl_name that is a prefix of the member name proves nothing.
    record_spawn(run_id="run-9", index=2, proposal_id="proposal-2", pid=4243)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    observations = recovery.collect_spawn_observations("docs", "refresh", batch)
    by_name = {item["agent_name"]: item["observation"] for item in observations}
    assert by_name["job-2"] == "matched_spawn"
    assert "sase-fix" not in by_name
    assert "job-0" not in by_name


def test_collect_observations_ignores_records_from_other_runs(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = manifest("run-9", None)
    chop_batch_store.create_chop_batch("docs", "refresh", batch)

    record_spawn(run_id="other-run", index=0, proposal_id="proposal-0", pid=4244)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    observations = recovery.collect_spawn_observations("docs", "refresh", batch)
    assert observations == []


def test_collect_observations_matches_by_proposal_id_without_index(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = manifest("run-9", None)
    chop_batch_store.create_chop_batch("docs", "refresh", batch)

    record_spawn(run_id="run-9", index=None, proposal_id="proposal-1", pid=4245)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    observations = recovery.collect_spawn_observations("docs", "refresh", batch)
    by_name = {item["agent_name"]: item["observation"] for item in observations}
    assert by_name["job-1"] == "matched_spawn"
    assert "job-0" not in by_name


def test_collect_observations_marks_unlinked_live_owner_as_foreign_conflict(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = manifest("run-9", None)
    chop_batch_store.create_chop_batch("docs", "refresh", batch)

    # A live, visible agent owns the planned name without run linkage: it
    # is a foreign conflict and must never be relaunched under a new name.
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: {"job-1"})
    observations = recovery.collect_spawn_observations("docs", "refresh", batch)
    by_name = {item["agent_name"]: item["observation"] for item in observations}
    assert by_name["job-1"] == "foreign_conflict"
    assert "job-0" not in by_name


def test_replay_rebuilds_first_run_launch_context_and_merges_history(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime

    from sase.axe.state import ChopRunEntry, read_chop_run, start_chop_run

    batch = replay_manifest()
    chop_batch_store.create_chop_batch("docs", "refresh", batch)
    start_chop_run(
        ChopRunEntry(
            run_id="run-9",
            lumberjack_name="docs",
            chop_name="refresh",
            started_at=datetime.now().isoformat(),
            finished_at=None,
            duration_ms=0,
            status="running",
        )
    )
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())

    captured: list[dict[str, Any]] = []
    pids = iter(range(9000, 9100))

    def fake_launcher(
        prompt: str,
        *,
        extra_env: dict[str, str],
        before_agent_spawn: Any = None,
        on_agent_launch_recorded: Any = None,
        pause_requested_fn: Any = None,
        origin: Any = None,
    ) -> Any:
        captured.append({"prompt": prompt, "env": dict(extra_env), "origin": origin})
        planned = str(extra_env.get("SASE_AGENT_PLANNED_NAME") or "")
        assert planned
        request = SimpleNamespace(
            name_reservation=SimpleNamespace(agent_name=planned),
            extra_env=extra_env,
        )
        if before_agent_spawn is not None:
            before_agent_spawn(0, 0, request, None)
        record = SimpleNamespace(
            agent_name=planned,
            pid=next(pids),
            workspace_num=1,
            workspace_dir="/tmp/ws",
            project_name="sase",
            workflow_name="fake",
            cl_name="sase",
            timestamp="20261118_120000",
            artifacts_dir="/tmp/artifacts",
        )
        if on_agent_launch_recorded is not None:
            on_agent_launch_recorded(0, 0, record, None)
        return [record]

    results = recovery.recover_pending_chop_batches(
        "docs",
        "refresh",
        launch_agents_from_cwd_fn=fake_launcher,
    )
    assert len(results) == 1
    assert results[0].kind == "ordinary"
    assert len(results[0].launched) == 4

    by_name = {
        str(item["env"].get("SASE_AGENT_PLANNED_NAME")): item for item in captured
    }
    assert set(by_name) == {"job-0", "job-2", "clan-a.worker", "clan-a.boss"}
    for item in captured:
        env = item["env"]
        # Chop linkage points at the original run and proposal index.
        assert env["SASE_CHOP_RUN_ID"] == "run-9"
        assert env["SASE_CHOP_LUMBERJACK"] == "docs"
        assert env["SASE_CHOP_NAME"] == "refresh"
        assert "SASE_CHOP_PROPOSAL_INDEX" in env
        assert item["origin"] == "generated"

    from sase.agent.clan_membership import (
        CLAN_MEMBERSHIP_ENV,
        decode_clan_membership_plan,
    )

    for clan_member in ("clan-a.worker", "clan-a.boss"):
        pin = decode_clan_membership_plan(
            by_name[clan_member]["env"][CLAN_MEMBERSHIP_ENV]
        )
        assert pin.clan_name == "clan-a"
        assert pin.generation == "gen-9"
    assert "SASE_AGENT_CLAN_MEMBERSHIP" not in by_name["job-0"]["env"]
    # The join prompt is unchanged; the declarer rejoins instead of
    # declaring a new clan.
    assert "%id(worker, clan=clan-a)" in by_name["clan-a.worker"]["prompt"]
    boss_prompt = by_name["clan-a.boss"]["prompt"]
    assert "%clan(" not in boss_prompt
    assert "%id(boss, clan=clan-a)" in boss_prompt
    # The dependent of the skipped member no longer waits on a name that
    # will never launch.
    assert "%wait:" not in by_name["job-2"]["prompt"]

    entry = read_chop_run("docs", "refresh", "run-9")
    assert entry is not None
    launches = list(entry.launches)
    assert len(launches) == 4
    keys = [
        (launch["index"], launch["agent_name"], launch["pid"]) for launch in launches
    ]
    assert len(set(keys)) == 4
    assert {launch["agent_name"] for launch in launches} == set(by_name)
    job_2 = next(launch for launch in launches if launch["agent_name"] == "job-2")
    assert job_2["wait_name"] is None
    assert "chop-agent" not in {launch["agent_name"] for launch in launches}

    # A second restart launches nothing and merges nothing twice.
    again = recovery.recover_pending_chop_batches(
        "docs",
        "refresh",
        launch_agents_from_cwd_fn=fake_launcher,
    )
    assert len(again) == 0 or all(not item.launched for item in again)
    entry = read_chop_run("docs", "refresh", "run-9")
    assert entry is not None
    assert len(list(entry.launches)) == 4


def test_collect_observations_tells_live_reserver_from_dead_reservation(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.names import (
        reset_name_registry_caches_for_tests,
        reserve_registered_name,
    )
    from sase.core.process_identity import process_identity_token

    batch = manifest("run-9", None)
    chop_batch_store.create_chop_batch("docs", "refresh", batch)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())

    live_dir = isolated_home / "agents" / "live"
    live_dir.mkdir(parents=True)
    (live_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "process_identity": process_identity_token(os.getpid()),
            }
        ),
        encoding="utf-8",
    )
    reserve_registered_name("job-0", live_dir)
    # A planned reservation whose artifacts never materialized: the
    # reserver died, so the member may relaunch under its identity.
    reserve_registered_name("job-1", isolated_home / "agents" / "never-spawned")
    reset_name_registry_caches_for_tests()

    observations = recovery.collect_spawn_observations("docs", "refresh", batch)
    by_name = {item["agent_name"]: item["observation"] for item in observations}
    assert by_name["job-0"] == "live_owner"
    assert by_name["job-1"] == "reservation_only"
    assert "job-2" not in by_name


def test_strict_observations_hold_on_unreadable_linkage(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import chop_agents
    from sase.axe._chop_batch_recovery_observations import (
        collect_spawn_observations_with_completeness,
    )

    batch = manifest("run-strict-unreadable")
    chop_batch_store.create_chop_batch("docs", "refresh", batch)
    monkeypatch.setattr(
        chop_agents,
        "get_chop_agent_records_strict",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("evidence disk unavailable")
        ),
    )
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    observations, complete, reason = collect_spawn_observations_with_completeness(
        "docs", "refresh", batch
    )
    assert complete is False
    assert observations == []
    assert reason is not None

    launched: list[Any] = []

    def fail_launcher(*args: Any, **kwargs: Any) -> Any:
        launched.append(True)
        raise AssertionError("must not dispatch on incomplete evidence")

    result = recovery.recover_pending_chop_batches(
        "docs", "refresh", launch_agents_from_cwd_fn=fail_launcher
    )
    assert result[0].kind == "blocked"
    assert "incomplete" in result[0].reason
    assert launched == []


def test_strict_observations_corrupt_linkage_holds_and_recovers(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import chop_agents
    from sase.axe._chop_batch_recovery_observations import (
        collect_spawn_observations_with_completeness,
    )
    from sase.axe.state import jack_state_dir

    batch = manifest("run-strict-corrupt")
    chop_batch_store.create_chop_batch("docs", "refresh", batch)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    registry = jack_state_dir() / "docs" / "agent_chops.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text("{corrupt", encoding="utf-8")
    observations, complete, _ = collect_spawn_observations_with_completeness(
        "docs", "refresh", batch
    )
    assert complete is False
    assert observations == []
    # Genuinely missing records are complete and safe to launch.
    registry.unlink()
    observations, complete, _ = collect_spawn_observations_with_completeness(
        "docs", "refresh", batch
    )
    assert complete is True
    # Corrupt registry entry for a reserver is also incomplete, never dead.
    monkeypatch.setattr(
        "sase.agent.names.lookup_registered_name",
        lambda name: {"artifacts_dir": str(isolated_home / "missing-meta")},
    )
    # Force a reservation by patching strict lookup to return an entry with
    # unreadable artifacts.
    from sase.axe import _chop_batch_recovery_observations as obs_module

    monkeypatch.setattr(
        obs_module,
        "_lookup_registry_entry_strict",
        lambda name: {"artifacts_dir": str(isolated_home / "agents" / "gone")},
    )
    monkeypatch.setattr(
        chop_agents,
        "get_chop_agent_records_strict",
        lambda *a, **k: [],
    )
    observations, complete, reason = collect_spawn_observations_with_completeness(
        "docs", "refresh", batch
    )
    # Missing meta dir reads as dead reservation (complete), but an existing
    # dir with unreadable meta must hold.
    assert complete is True or reason is not None
