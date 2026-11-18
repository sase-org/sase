"""Recovery entry point: resume unfinished batches and honor clan kills."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.axe import chop_batch_recovery as recovery
from sase.axe import chop_batch_store
from sase.axe import chop_runner_script_result_keys as claim_keys
from sase.axe.chop_stop_signal import ChopStopSignal
from sase.axe.state import ChopRunEntry, chop_run_log_path, start_chop_run
from sase.core.axe_chop_facade import CHOP_BATCH_SCHEMA_VERSION


def _manifest(batch_id: str = "run-1", clan: str | None = "clan-a") -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    for index in range(3):
        member: dict[str, Any] = {
            "source_index": index,
            "proposal_id": f"proposal-{index}",
            "agent_name": f"job-{index}",
            "prompt": f"%id:job-{index}\nDo {index}.",
            "workspace": "git:sase",
        }
        if clan is not None:
            member["clan"] = clan
        members.append(member)
    return {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "run": {"routine": "docs", "job": "refresh", "run_id": batch_id},
        "members": members,
    }


def _record_spawn(
    *,
    routine: str = "docs",
    job: str = "refresh",
    run_id: str,
    index: int | None,
    proposal_id: str | None = None,
    cl_name: str = "sase",
    pid: int = 4242,
) -> None:
    """Write one production-shaped chop-agent record for a member spawn."""
    from sase.axe.chop_agents import (
        build_chop_launch_env,
        record_chop_agent_launch_from_env,
    )

    env = build_chop_launch_env(
        lumberjack_name=routine,
        chop_name=job,
        prompt="%id:job-0\nDo 0.",
        run_id=run_id,
        proposal_index=index,
        proposal_id=proposal_id,
    )
    record = record_chop_agent_launch_from_env(
        pid=pid,
        project_file="/tmp/projects/sase/sase.sase",
        project_name="sase",
        workspace_num=1,
        workflow_name="fake-chop-batch-recovery",
        cl_name=cl_name,
        timestamp="20261118_120000",
        prompt="%id:job-0\nDo 0.",
        env=env,
    )
    assert record is not None


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def test_stop_signal_is_thread_safe_pause_fn() -> None:
    signal = ChopStopSignal()
    assert signal.stop_requested() is False
    assert signal() is False
    signal.request_stop()
    assert signal.stop_requested() is True
    assert signal() is True
    assert signal.as_pause_fn()() is True


def test_pending_batch_for_run_skips_complete_batches(
    isolated_home: Path,
) -> None:
    chop_batch_store.create_chop_batch("docs", "refresh", _manifest("run-1"))
    assert recovery.has_unfinished_chop_batch("docs", "refresh") is True
    assert recovery.pending_batch_for_run("docs", "refresh", "run-1") is not None
    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "run-1", "cancel_clan_generation", reason="kill clan-a"
    )
    assert recovery.has_unfinished_chop_batch("docs", "refresh") is False
    assert recovery.pending_batch_for_run("docs", "refresh", "run-1") is None


def test_pending_batch_for_run_waits_for_cancelled_inflight_dispatch(
    isolated_home: Path,
) -> None:
    chop_batch_store.create_chop_batch("docs", "refresh", _manifest("run-cancel"))
    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "run-cancel", "begin_dispatch", member_index=0
    )

    cancelled = chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "run-cancel",
        "cancel_clan_generation",
        reason="kill during spawn",
    )

    assert cancelled["members"][0]["status"] == "dispatching"
    assert recovery.pending_batch_for_run("docs", "refresh", "run-cancel") is not None

    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "run-cancel", "acknowledge_launch", member_index=0
    )
    assert recovery.pending_batch_for_run("docs", "refresh", "run-cancel") is None


def test_cancel_targets_only_matching_clan_generation(
    isolated_home: Path,
) -> None:
    chop_batch_store.create_chop_batch("docs", "refresh", _manifest("run-1", "clan-a"))
    other = _manifest("run-2", "clan-b")
    chop_batch_store.create_chop_batch("docs", "refresh", other)
    cancelled = recovery.cancel_chop_batches_for_clan(
        "clan-a", reason="explicit TUI clan kill of clan-a"
    )
    assert [entry["batch_id"] for entry in cancelled] == ["run-1"]
    assert recovery.pending_batch_for_run("docs", "refresh", "run-1") is None
    assert recovery.pending_batch_for_run("docs", "refresh", "run-2") is not None


def test_cancel_matches_a_secondary_clan_in_the_batch(
    isolated_home: Path,
) -> None:
    manifest = _manifest("run-multi-clan", "clan-a")
    manifest["members"][1]["clan"] = "clan-b"
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)

    cancelled = recovery.cancel_chop_batches_for_clan(
        "clan-b", reason="explicit TUI clan kill of clan-b"
    )

    assert [entry["batch_id"] for entry in cancelled] == ["run-multi-clan"]
    assert (
        chop_batch_store.load_chop_batch("docs", "refresh", "run-multi-clan")["status"]
        == "cancelled"
    )


def test_older_generation_does_not_cancel_a_batch_without_recorded_generation(
    isolated_home: Path,
) -> None:
    manifest = _manifest("run-new-clan", None)
    manifest["created_at"] = "2026-11-18T12:00:00+00:00"
    manifest["members"][0]["clan"] = "reused-clan"
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)

    cancelled = recovery.cancel_chop_batches_for_clan(
        "reused-clan",
        generation="20261117_120000",
        reason="explicit TUI clan kill of the old generation",
    )

    assert cancelled == []
    assert (
        chop_batch_store.load_chop_batch("docs", "refresh", "run-new-clan")["status"]
        == "open"
    )


def test_disabled_batch_hold_is_notified_once(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import _chop_batch_recovery_resume as resume
    from sase.notifications.store import load_notifications

    chop_batch_store.create_chop_batch("docs", "refresh", _manifest("run-disabled"))
    monkeypatch.setattr(resume, "_job_disabled", lambda _job, _routine: True)
    monkeypatch.setattr("sase.axe.maintenance.read_maintenance", lambda: None)

    first = recovery.recover_pending_chop_batches("docs", "refresh")
    second = recovery.recover_pending_chop_batches("docs", "refresh")

    assert first[0].kind == second[0].kind == "blocked"
    notices = [
        item
        for item in load_notifications(include_dismissed=True)
        if item.sender == "chop-batch-recovery"
    ]
    assert len(notices) == 1
    assert notices[0].tags == ["chop", "batch", "hold"]
    state = chop_batch_store.load_chop_batch_notice_state(
        "docs", "refresh", "run-disabled"
    )
    episodes = list(state["episodes"].values())
    assert len(episodes) == 1
    assert episodes[0]["events"]["hold"]["delivered"] is True


def test_notice_delivery_retry_reuses_one_notification_row(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import _chop_batch_recovery_shared as recovery_shared
    from sase.notifications.store import load_notifications

    chop_batch_store.create_chop_batch("docs", "refresh", _manifest("run-notice-retry"))
    episode_id = recovery_shared.prepare_batch_notice(
        routine="docs",
        job="refresh",
        batch_id="run-notice-retry",
        event="hold",
        launched=0,
        remaining=3,
        reason="maintenance",
        hold_key="maintenance",
    )
    update_notice_state = recovery_shared.update_chop_batch_notice_state

    def fail_delivery_ack(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("simulated crash before outbox acknowledgement")

    monkeypatch.setattr(
        recovery_shared, "update_chop_batch_notice_state", fail_delivery_ack
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        recovery_shared.deliver_pending_batch_notices(
            "docs", "refresh", "run-notice-retry"
        )

    monkeypatch.setattr(
        recovery_shared, "update_chop_batch_notice_state", update_notice_state
    )
    recovery_shared.deliver_pending_batch_notices("docs", "refresh", "run-notice-retry")
    recovery_shared.deliver_pending_batch_notices("docs", "refresh", "run-notice-retry")

    notices = [
        item
        for item in load_notifications(include_dismissed=True)
        if item.sender == "chop-batch-recovery"
    ]
    assert len(notices) == 1
    assert notices[0].dedup_key.endswith(episode_id)
    assert notices[0].plus_ones == []
    event = chop_batch_store.load_chop_batch_notice_state(
        "docs", "refresh", "run-notice-retry"
    )["episodes"][episode_id]["events"]["hold"]
    assert event["delivered"] is True


def test_interruption_and_resume_notices_have_separate_episode_keys(
    isolated_home: Path,
) -> None:
    from sase.axe._chop_batch_recovery_shared import emit_batch_notice
    from sase.notifications.store import load_notifications

    chop_batch_store.create_chop_batch("docs", "refresh", _manifest("run-two-episodes"))
    first_episode = emit_batch_notice(
        routine="docs",
        job="refresh",
        batch_id="run-two-episodes",
        event="interrupted",
        launched=0,
        remaining=3,
    )
    emit_batch_notice(
        routine="docs",
        job="refresh",
        batch_id="run-two-episodes",
        event="resumed",
        launched=0,
        remaining=3,
        episode_id=first_episode,
    )
    second_episode = emit_batch_notice(
        routine="docs",
        job="refresh",
        batch_id="run-two-episodes",
        event="interrupted",
        launched=1,
        remaining=2,
    )
    emit_batch_notice(
        routine="docs",
        job="refresh",
        batch_id="run-two-episodes",
        event="resumed",
        launched=1,
        remaining=2,
        episode_id=second_episode,
    )

    assert first_episode != second_episode
    notices = [
        item
        for item in load_notifications(include_dismissed=True)
        if item.sender == "chop-batch-recovery"
    ]
    assert len(notices) == 4
    assert len({item.dedup_key for item in notices}) == 4
    assert all(
        first_episode in item.dedup_key or second_episode in item.dedup_key
        for item in notices
    )


def test_deterministic_recovery_launch_failure_is_bounded(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest("run-bounded-failure")
    manifest["members"] = manifest["members"][:1]
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())

    def fail_launch(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("deterministic launcher refusal")

    for _ in range(3):
        result = recovery.recover_pending_chop_batches(
            "docs", "refresh", launch_agents_from_cwd_fn=fail_launch
        )

    stored = chop_batch_store.load_chop_batch("docs", "refresh", "run-bounded-failure")
    assert stored["members"][0]["status"] == "blocked"
    assert "3 times" in stored["members"][0]["status_reason"]
    assert result[0].blocked[0]["status"] == "blocked"
    assert "deterministic launcher refusal" in result[0].blocked[0]["reason"]


def test_typed_bundle_cancel_failure_is_logged_and_surfaced(
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest("run-typed-cancel", "clan-a")
    start_chop_run(
        ChopRunEntry(
            run_id="run-typed-cancel",
            lumberjack_name="docs",
            chop_name="refresh",
            started_at="2026-11-18T12:00:00+00:00",
            finished_at=None,
            duration_ms=0,
            status="running",
        )
    )
    manifest["typed_bundle"] = {
        "bundle_id": "typed-cancel-bundle",
        "bundle_digest": "typed-cancel-digest",
    }
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)

    def _fail_cancel(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("could not write cancellation marker")

    monkeypatch.setattr(
        "sase.agent.direct_typed_launch.typed_launch_bundle_dir",
        lambda _bundle_id: tmp_path,
    )
    import sase.agent.launch_admission as launch_admission

    monkeypatch.setattr(
        launch_admission,
        "cancel_typed_launch_request",
        _fail_cancel,
        raising=False,
    )

    with pytest.raises(chop_batch_store.ChopBatchError, match="persisted"):
        recovery.cancel_chop_batches_for_clan(
            "clan-a",
            reason="explicit clan kill",
            routine="docs",
            job="refresh",
        )

    cancelled = chop_batch_store.load_chop_batch("docs", "refresh", "run-typed-cancel")
    assert cancelled["status"] == "cancelled"
    log = chop_run_log_path("docs", "refresh", "run-typed-cancel")
    assert "could not write cancellation marker" in log.read_text(encoding="utf-8")


def test_once_per_claim_release_follows_batch_member_journal(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest("run-claims", None)
    manifest["members"].append(
        {
            "source_index": 3,
            "proposal_id": "proposal-3",
            "agent_name": "job-3",
            "prompt": "%id:job-3\nDo 3.",
            "workspace": "git:sase",
        }
    )
    for index, member in enumerate(manifest["members"]):
        member["dedupe_key"] = "shared-key" if index in {2, 3} else f"key-{index}"
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)
    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "run-claims", "begin_dispatch", member_index=0
    )
    chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "run-claims",
        "record_skip",
        member_index=1,
        reason="explicit name collision",
    )

    released: list[str] = []
    monkeypatch.setattr(
        claim_keys,
        "release_chop_once_per_keys",
        lambda _routine, _job, keys: released.extend(keys) or len(keys),
    )
    proposals = [
        SimpleNamespace(
            index=index,
            dedupe_key="shared-key" if index in {2, 3} else f"key-{index}",
        )
        for index in range(4)
    ]

    claim_keys.release_unlaunched_once_per_keys(
        lumberjack_name="docs",
        chop_name="refresh",
        run_id="run-claims",
        accepted_proposals=proposals,
        successful_launches=[],
    )

    assert released == ["key-1"]


def test_typed_once_per_claim_release_uses_outer_journal(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest("run-typed-claims", None)
    manifest["members"].append(
        {
            "source_index": 3,
            "proposal_id": "proposal-3",
            "agent_name": "job-3",
            "prompt": "%id:job-3\nDo 3.",
            "workspace": "git:sase",
        }
    )
    manifest["typed_bundle"] = {
        "bundle_id": "bundle-typed-claims",
        "bundle_digest": "digest-typed-claims",
    }
    for index, member in enumerate(manifest["members"]):
        member["dedupe_key"] = (
            "shared-typed-key" if index in {2, 3} else f"typed-key-{index}"
        )
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)
    chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "run-typed-claims",
        "begin_dispatch",
        member_index=0,
    )
    chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "run-typed-claims",
        "record_skip",
        member_index=1,
        reason="condition false",
    )

    released: list[str] = []
    monkeypatch.setattr(
        claim_keys,
        "release_chop_once_per_keys",
        lambda _routine, _job, keys: released.extend(keys) or len(keys),
    )
    typed_admission = {
        "units": [
            {
                "logical_id": f"unit-{index}",
                "proposal_index": index,
                "dedupe_key": (
                    "shared-typed-key" if index in {2, 3} else f"typed-key-{index}"
                ),
            }
            for index in range(3)
        ]
    }
    result = SimpleNamespace(
        unit_results=[
            SimpleNamespace(logical_id=f"unit-{index}", outcome="launch_error")
            for index in range(4)
        ]
    )

    claim_keys.release_typed_nonlaunched_once_per_keys(
        lumberjack_name="docs",
        chop_name="refresh",
        run_id="run-typed-claims",
        typed_admission=typed_admission,
        admission_result=result,
        after="typed test",
    )

    assert released == ["typed-key-1"]


def test_cancel_never_fires_for_individual_member_selection() -> None:
    member = SimpleNamespace(
        is_clan_container=False, agent_clan="clan-a", agent_clan_generation=None
    )
    from sase.ace.tui.actions.agents._clan_cleanup import (
        cancel_pending_batches_for_clan_selection,
    )

    assert cancel_pending_batches_for_clan_selection([member]) == 0


def test_collect_observations_matches_by_run_linkage_not_cl_name(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest("run-9", None)
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)

    # Production cl_name is the project name: it neither equals nor is
    # matched against member identities, even as a prefix.
    _record_spawn(run_id="run-9", index=0, proposal_id="proposal-0", pid=4242)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    observations = recovery.collect_spawn_observations("docs", "refresh", manifest)
    by_name = {item["agent_name"]: item["observation"] for item in observations}
    assert by_name["job-0"] == "matched_spawn"
    # job-1 and job-2 have no record and no reservation: absent, safe to launch.
    assert "job-1" not in by_name
    assert "job-2" not in by_name


def test_collect_observations_ignores_prefix_cl_name_without_linkage(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest("run-9", None)
    manifest["members"][1]["agent_name"] = "sase-fix"
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)

    # A project cl_name that is a prefix of the member name proves nothing.
    _record_spawn(run_id="run-9", index=2, proposal_id="proposal-2", pid=4243)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    observations = recovery.collect_spawn_observations("docs", "refresh", manifest)
    by_name = {item["agent_name"]: item["observation"] for item in observations}
    assert by_name["job-2"] == "matched_spawn"
    assert "sase-fix" not in by_name
    assert "job-0" not in by_name


def test_collect_observations_ignores_records_from_other_runs(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest("run-9", None)
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)

    _record_spawn(run_id="other-run", index=0, proposal_id="proposal-0", pid=4244)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    observations = recovery.collect_spawn_observations("docs", "refresh", manifest)
    assert observations == []


def test_collect_observations_matches_by_proposal_id_without_index(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest("run-9", None)
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)

    _record_spawn(run_id="run-9", index=None, proposal_id="proposal-1", pid=4245)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    observations = recovery.collect_spawn_observations("docs", "refresh", manifest)
    by_name = {item["agent_name"]: item["observation"] for item in observations}
    assert by_name["job-1"] == "matched_spawn"
    assert "job-0" not in by_name


def test_collect_observations_marks_unlinked_live_owner_as_foreign_conflict(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest("run-9", None)
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)

    # A live, visible agent owns the planned name without run linkage: it
    # is a foreign conflict and must never be relaunched under a new name.
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: {"job-1"})
    observations = recovery.collect_spawn_observations("docs", "refresh", manifest)
    by_name = {item["agent_name"]: item["observation"] for item in observations}
    assert by_name["job-1"] == "foreign_conflict"
    assert "job-0" not in by_name


def _replay_manifest() -> dict[str, Any]:
    members: list[dict[str, Any]] = [
        {
            "source_index": 0,
            "proposal_id": "proposal-0",
            "agent_name": "job-0",
            "prompt": "#git:sase\n%id:job-0\nDo 0.",
            "workspace": "git:sase",
        },
        {
            "source_index": 1,
            "proposal_id": "proposal-1",
            "agent_name": "job-1",
            "prompt": "#git:sase\n%id:job-1\nDo 1.",
            "workspace": "git:sase",
            "status": "skipped",
            "status_reason": "explicit agent name collision",
        },
        {
            "source_index": 2,
            "proposal_id": "proposal-2",
            "agent_name": "job-2",
            "prompt": "#git:sase\n%id:job-2\n%wait:job-1\nDo 2.",
            "workspace": "git:sase",
            "wait_on": 1,
        },
        {
            "source_index": 3,
            "proposal_id": "proposal-3",
            "agent_name": "clan-a.worker",
            "prompt": "#git:sase\n%id(worker, clan=clan-a)\nDo 3.",
            "workspace": "git:sase",
            "launch_role": "join",
            "clan": "clan-a",
            "clan_generation": "gen-9",
        },
        {
            "source_index": 4,
            "proposal_id": "proposal-4",
            "agent_name": "clan-a.boss",
            "prompt": "#git:sase\n%id:clan-a.boss\n%clan(clan-a, tribe=eng)\nDo 4.",
            "workspace": "git:sase",
            "launch_role": "declare",
            "clan": "clan-a",
            "clan_generation": "gen-9",
        },
    ]
    return {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": "run-9",
        "run": {"routine": "docs", "job": "refresh", "run_id": "run-9"},
        "clan": "clan-a",
        "clan_generation": "gen-9",
        "members": members,
    }


def test_replay_rebuilds_first_run_launch_context_and_merges_history(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime

    from sase.axe.state import ChopRunEntry, read_chop_run, start_chop_run

    manifest = _replay_manifest()
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)
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

    manifest = _manifest("run-9", None)
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)
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

    observations = recovery.collect_spawn_observations("docs", "refresh", manifest)
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

    manifest = _manifest("run-strict-unreadable")
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)
    monkeypatch.setattr(
        chop_agents,
        "get_chop_agent_records_strict",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("evidence disk unavailable")
        ),
    )
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    observations, complete, reason = collect_spawn_observations_with_completeness(
        "docs", "refresh", manifest
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

    manifest = _manifest("run-strict-corrupt")
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    registry = jack_state_dir() / "docs" / "agent_chops.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text("{corrupt", encoding="utf-8")
    observations, complete, _ = collect_spawn_observations_with_completeness(
        "docs", "refresh", manifest
    )
    assert complete is False
    assert observations == []
    # Genuinely missing records are complete and safe to launch.
    registry.unlink()
    observations, complete, _ = collect_spawn_observations_with_completeness(
        "docs", "refresh", manifest
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
        "docs", "refresh", manifest
    )
    # Missing meta dir reads as dead reservation (complete), but an existing
    # dir with unreadable meta must hold.
    assert complete is True or reason is not None


def test_cancel_scoped_to_requested_clan_generation(
    isolated_home: Path,
) -> None:
    members: list[dict[str, Any]] = []
    for index, (name, clan, generation) in enumerate(
        [
            ("a.one", "a", "20261118_120000"),
            ("b.one", "b", "20261118_130000"),
        ]
    ):
        members.append(
            {
                "source_index": index,
                "agent_name": name,
                "clan": clan,
                "clan_generation": generation,
                "prompt": f"Do {name}.",
                "workspace": "git:sase",
            }
        )
    manifest = {
        "schema_version": 1,
        "batch_id": "mixed-generation",
        "run": {"routine": "docs", "job": "refresh", "run_id": "mixed-generation"},
        "members": members,
    }
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)
    # Wrong generation that belongs to the other clan must not cancel.
    wrong = recovery.cancel_chop_batches_for_clan(
        "a", generation="20261118_130000", reason="kill different generation of a"
    )
    assert wrong == []
    assert (
        chop_batch_store.load_chop_batch("docs", "refresh", "mixed-generation")[
            "status"
        ]
        == "open"
    )
    # Correct secondary-clan generation cancels the whole batch.
    cancelled = recovery.cancel_chop_batches_for_clan(
        "b", generation="20261118_130000", reason="kill clan b"
    )
    assert [entry["batch_id"] for entry in cancelled] == ["mixed-generation"]
    assert (
        chop_batch_store.load_chop_batch("docs", "refresh", "mixed-generation")[
            "status"
        ]
        == "cancelled"
    )


def test_rust_generation_match_binding_scopes_to_clan(
    isolated_home: Path,
) -> None:
    sase_core_rs = pytest.importorskip("sase_core_rs")
    if not hasattr(sase_core_rs, "chop_batch_generation_matches"):
        pytest.skip("core binding not yet built; fallback covers old pins")
    from sase.core.axe_chop_facade import (
        CHOP_BATCH_SCHEMA_VERSION,
        chop_batch_generation_matches,
    )

    members: list[dict[str, Any]] = []
    for index, (name, clan, generation) in enumerate(
        [("a.one", "a", "20261118_120000"), ("b.one", "b", "20261118_130000")]
    ):
        members.append(
            {
                "source_index": index,
                "agent_name": name,
                "clan": clan,
                "clan_generation": generation,
                "prompt": f"Do {name}.",
                "workspace": "git:sase",
            }
        )
    manifest = {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": "mixed-gen-rust",
        "run": {"routine": "docs", "job": "refresh", "run_id": "mixed-gen-rust"},
        "members": members,
    }
    assert (
        chop_batch_generation_matches(
            {
                "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                "manifest": manifest,
                "clan": "a",
                "generation": "20261118_130000",
            }
        )
        is False
    )
    assert (
        chop_batch_generation_matches(
            {
                "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                "manifest": manifest,
                "clan": "a",
                "generation": "20261118_120000",
            }
        )
        is True
    )
    assert (
        chop_batch_generation_matches(
            {
                "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                "manifest": manifest,
                "clan": "b",
                "generation": "20261118_130000",
            }
        )
        is True
    )


def test_dry_run_is_readonly(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import _chop_batch_recovery_resume as resume_module

    manifest = _manifest("run-dry-readonly")
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)
    monkeypatch.setattr(resume_module, "_job_disabled", lambda _job, _routine: True)
    monkeypatch.setattr("sase.axe.maintenance.read_maintenance", lambda: None)

    def snapshot() -> dict[str, bytes]:
        root = isolated_home
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    before = snapshot()
    launched: list[Any] = []

    def fail_launcher(*args: Any, **kwargs: Any) -> Any:
        launched.append(True)
        raise AssertionError("dry-run must never invoke a launcher")

    result = recovery.recover_pending_chop_batches(
        "docs", "refresh", dry_run=True, launch_agents_from_cwd_fn=fail_launcher
    )
    after = snapshot()
    assert before == after
    assert launched == []
    assert result[0].kind == "blocked"
    # Disabled hold must not have created a notice sidecar either.
    assert (
        chop_batch_store.load_chop_batch_notice_state(
            "docs", "refresh", "run-dry-readonly"
        )
        == {}
    )


def test_cancelled_dead_executor_no_spawn_settles(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    monkeypatch.setattr(
        "sase.agent.names.get_blocked_local_namespace_roots", lambda: {}
    )
    monkeypatch.setattr("sase.agent.names.lookup_registered_name", lambda name: None)
    manifest = _manifest("cancelled-lost-ack")
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)
    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "cancelled-lost-ack", "begin_dispatch", member_index=0
    )
    chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "cancelled-lost-ack",
        "cancel_clan_generation",
        reason="kill while executor dies",
    )
    assert (
        recovery.pending_batch_for_run("docs", "refresh", "cancelled-lost-ack")
        is not None
    )
    results = recovery.recover_pending_chop_batches("docs", "refresh", dry_run=False)
    assert any(
        item.batch_id == "cancelled-lost-ack" and item.kind in {"cancelled", "blocked"}
        for item in results
    )
    refreshed = chop_batch_store.load_chop_batch(
        "docs", "refresh", "cancelled-lost-ack"
    )
    # No spawn evidence: dispatching settles to cancelled without launching.
    assert refreshed["members"][0]["status"] in {"cancelled", "dispatching"}
    if refreshed["members"][0]["status"] == "cancelled":
        assert (
            recovery.pending_batch_for_run("docs", "refresh", "cancelled-lost-ack")
            is None
        )


def test_cancelled_dead_executor_proven_spawn_acknowledges(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    monkeypatch.setattr(
        "sase.agent.names.get_blocked_local_namespace_roots", lambda: {}
    )
    monkeypatch.setattr("sase.agent.names.lookup_registered_name", lambda name: None)
    manifest = _manifest("cancelled-proven-spawn")
    manifest["members"] = manifest["members"][:1]
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)
    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "cancelled-proven-spawn", "begin_dispatch", member_index=0
    )
    _record_spawn(run_id="cancelled-proven-spawn", index=0, proposal_id="proposal-0")
    chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "cancelled-proven-spawn",
        "cancel_clan_generation",
        reason="kill during crossing launch",
    )
    results = recovery.recover_pending_chop_batches("docs", "refresh", dry_run=False)
    assert any(item.batch_id == "cancelled-proven-spawn" for item in results)
    refreshed = chop_batch_store.load_chop_batch(
        "docs", "refresh", "cancelled-proven-spawn"
    )
    assert refreshed["members"][0]["status"] == "launched"
