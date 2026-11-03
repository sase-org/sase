"""Detached recovery retains real work and obeys the held-claim lifecycle."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sase.agent.staged_handoff import read_adoption_receipt, write_staged_handoff
from sase.axe.run_agent_exec_staged_recovery import recover_staged_handoff
from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline
from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from sase.turns.workspace_retention_surface import dismiss_terminal_workspace_retention
from sase.workspace_provider.occupant import (
    OccupantRecord,
    read_occupant_record,
    write_occupant_record,
)
from sase.workspace_provider.retention_record import read_workspace_retention_record
from tests.monitor._fixtures import write_project_file
from tests.test_staged_recovery_service import STAGED_ID, _record, _write_meta
from tests.turns.test_workspace_retention import _init_repo


@pytest.fixture
def origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_PROJECT_FILE", str(tmp_path / "wrong-project.sase"))
    artifacts = resolve_agent_artifact_timestamp_path(
        "proj", "ace-run", "20261028120000"
    )
    artifacts.mkdir(parents=True)
    checkout = _init_repo(tmp_path / "workspace")
    write_staged_handoff(_record(tmp_path, "pipe"), artifacts_dir=str(artifacts))
    _write_meta(artifacts, pid=999999)
    metadata_path = artifacts / "agent_meta.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.update(workspace_dir=str(checkout), workspace_num=2)
    metadata_path.write_text(json.dumps(metadata))
    capture_dirty_baseline(str(checkout), str(artifacts))
    claim = WorkspaceClaim(
        2, "run", "feature", pid=999999, artifacts_timestamp=artifacts.name
    )
    project_file = write_project_file(
        "proj", workspace_dir=str(checkout), running_claims=[claim]
    )
    write_occupant_record(
        str(checkout),
        OccupantRecord(
            pid=claim.pid,
            workflow=claim.workflow,
            project="proj",
            workspace_num=2,
            artifacts_timestamp=artifacts.name,
            cl_name="feature",
        ),
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery_facts.finalizer_settlement_refusal",
        lambda *_a, **_k: "finalizer instance 'commit' did not settle successfully",
    )
    for module in ("run_agent_exec_staged_recovery", "run_agent_exec_staged_retention"):
        monkeypatch.setattr(f"sase.axe.{module}.observe_runner", lambda _: "dead")
    return artifacts, checkout, project_file, claim


def _cleanup(monkeypatch, checkout, *, now, ttl=14):
    import sase.ace.scheduler.stale_running_cleanup as cleanup

    monkeypatch.setattr(cleanup, "is_process_running", lambda _: False)
    monkeypatch.setattr(cleanup, "_held_claim_ttl_days", lambda: ttl)
    monkeypatch.setattr(cleanup, "_now", lambda: now)
    monkeypatch.setattr(
        cleanup,
        "get_workspace_directory_for_num",
        lambda *_a, **_k: (str(checkout), ""),
    )
    return cleanup.cleanup_stale_running_entries()


@pytest.mark.parametrize("mode", ["automatic", "explicit"])
@pytest.mark.parametrize("dirty_repo", ["primary", "linked", "clean"])
def test_recovery_settles_dead_origin_through_shared_policy(
    origin, tmp_path, monkeypatch, mode, dirty_repo
):
    artifacts, checkout, project_file, _ = origin
    dirty_path = checkout / "tracked.txt"
    if dirty_repo == "linked":
        from sase._linked_repo_markers import record_opened_external_repo

        linked = _init_repo(tmp_path / "linked")
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        record_opened_external_repo(
            "widget", str(linked), reason="work", opened_at="2026-10-28T12:00:00Z"
        )
        dirty_path = linked / "tracked.txt"
    if dirty_repo != "clean":
        dirty_path.write_text("retained work\n")

    result = recover_staged_handoff(str(artifacts), mode=mode)

    assert not result.adopted and result.action == "hold"
    receipt = read_adoption_receipt(str(artifacts))
    if mode == "explicit":
        assert receipt is not None and receipt["outcome"] == "handoff_not_adopted"
    else:
        # Automatic probes remain eligible for retry without publishing a receipt.
        assert receipt is None
    done = json.loads((artifacts / "done.json").read_text())
    assert done["outcome"] == "failed"
    assert "handoff_not_adopted" in done["error"]
    claims = get_claimed_workspaces(project_file)
    record = read_workspace_retention_record(artifacts)
    if dirty_repo == "clean":
        assert claims == []
        assert read_occupant_record(str(checkout)) is None
        assert record is None
        return
    assert len(claims) == 1 and claims[0].pinned
    assert record is not None and record.terminal and record.unresolved
    assert record.staged_id == STAGED_ID
    assert record.snapshot_paths
    if dirty_repo == "linked":
        assert "external:widget" in record.affected_repo_ids
    assert dirty_path.read_text() == "retained work\n"
    assert _cleanup(monkeypatch, checkout, now=datetime(2026, 10, 29, 12)) == 0
    assert get_claimed_workspaces(project_file)[0].pinned

    assert dismiss_terminal_workspace_retention(project_file, artifacts)
    settled = (artifacts / "diagnostics/workspace_retention.json").read_bytes()
    recover_staged_handoff(str(artifacts), mode=mode)
    assert get_claimed_workspaces(project_file) == []
    assert (artifacts / "diagnostics/workspace_retention.json").read_bytes() == settled
    assert dirty_path.read_text() == "retained work\n"


@pytest.mark.parametrize("ttl,age,released", [(14, 13, 0), (14, 15, 1), (0, 400, 0)])
def test_staged_terminal_hold_obeys_ttl(origin, monkeypatch, ttl, age, released):
    artifacts, checkout, project_file, _ = origin
    (checkout / "tracked.txt").write_text("held\n")
    (artifacts / "done.json").write_text('{"outcome":"failed","error":"original"}')
    recover_staged_handoff(str(artifacts), mode="explicit")
    assert json.loads((artifacts / "done.json").read_text())["error"] == "original"

    assert (
        _cleanup(
            monkeypatch,
            checkout,
            now=datetime(2026, 10, 28, 12) + timedelta(days=age),
            ttl=ttl,
        )
        == released
    )
    record = read_workspace_retention_record(artifacts)
    assert record is not None and record.unresolved == (not released)
    assert bool(get_claimed_workspaces(project_file)) == (not released)
    assert (read_occupant_record(str(checkout)) is None) == bool(released)


@pytest.mark.parametrize("runner", ["alive", "unknown"])
def test_recovery_does_not_terminalize_live_or_unknown_origin(
    origin, monkeypatch, runner
):
    artifacts, checkout, project_file, _ = origin
    (checkout / "tracked.txt").write_text("work in progress\n")
    for module in ("run_agent_exec_staged_recovery", "run_agent_exec_staged_retention"):
        monkeypatch.setattr(f"sase.axe.{module}.observe_runner", lambda _: runner)
    recover_staged_handoff(str(artifacts), mode="explicit")
    assert not (artifacts / "done.json").exists()
    assert read_workspace_retention_record(artifacts) is None
    assert not get_claimed_workspaces(project_file)[0].pinned


def test_explicit_user_kill_does_not_create_a_terminal_hold(origin):
    artifacts, checkout, project_file, _ = origin
    (checkout / "tracked.txt").write_text("work\n")
    meta_path = artifacts / "agent_meta.json"
    metadata = json.loads(meta_path.read_text())
    metadata["handoff_protocol"] = "killed"
    meta_path.write_text(json.dumps(metadata))

    result = recover_staged_handoff(str(artifacts), mode="explicit")

    assert result.action == "refuse"
    assert read_workspace_retention_record(artifacts) is None
    assert not (artifacts / "done.json").exists()
    assert not get_claimed_workspaces(project_file)[0].pinned


def test_success_receipt_prevents_late_held_writer_from_settling_workspace(origin):
    from sase.agent.staged_handoff import acquire_adoption_lock, write_adoption_receipt
    from sase.axe._run_agent_exec_staged_recovery_shared import write_held_locked

    artifacts, checkout, project_file, claim = origin
    (checkout / "tracked.txt").write_text("successor work\n")
    write_adoption_receipt(
        {
            "staged_id": STAGED_ID,
            "adopted_at": "2026-10-28T12:01:00Z",
            "outcome": "adopted",
            "refs": {},
        },
        artifacts_dir=str(artifacts),
    )
    with acquire_adoption_lock(artifacts):
        write_held_locked(STAGED_ID, "late refusal", artifacts_dir=str(artifacts))

    assert get_claimed_workspaces(project_file) == [claim]
    assert read_workspace_retention_record(artifacts) is None
    assert read_adoption_receipt(str(artifacts))["outcome"] == "adopted"


@pytest.mark.parametrize("race", ["before_release", "after_release"])
def test_cleanup_expiry_preserves_successor_custody(origin, monkeypatch, race):
    import sase.ace.scheduler.stale_running_cleanup as cleanup

    artifacts, checkout, project_file, claim = origin
    (checkout / "tracked.txt").write_text("held\n")
    recover_staged_handoff(str(artifacts), mode="explicit")
    successor = replace(claim, pid=123456, artifacts_timestamp="20261120120000")
    release = cleanup.release_workspace

    def transfer():
        write_project_file(
            "proj", workspace_dir=str(checkout), running_claims=[successor]
        )
        write_occupant_record(
            str(checkout),
            OccupantRecord(
                pid=successor.pid,
                workflow=successor.workflow,
                project="proj",
                workspace_num=2,
                artifacts_timestamp=successor.artifacts_timestamp,
                cl_name="feature",
            ),
        )

    def racing_release(*args, **kwargs):
        if race == "before_release":
            transfer()
        result = release(*args, **kwargs)
        if race == "after_release":
            transfer()
        return result

    monkeypatch.setattr(cleanup, "release_workspace", racing_release)
    assert _cleanup(monkeypatch, checkout, now=datetime(2026, 11, 20, 12)) == (
        race == "after_release"
    )
    assert get_claimed_workspaces(project_file) == [successor]
    occupant = read_occupant_record(str(checkout))
    assert occupant is not None and occupant.pid == successor.pid
    before = (artifacts / "diagnostics/workspace_retention.json").read_bytes()
    recover_staged_handoff(str(artifacts), mode="explicit")
    assert get_claimed_workspaces(project_file) == [successor]
    assert (artifacts / "diagnostics/workspace_retention.json").read_bytes() == before


def test_successful_readopt_settles_record_and_blocks_late_hold(origin, monkeypatch):
    """A proven transfer settles the hold; a delayed callback cannot recreate it."""
    from sase.axe._run_agent_exec_staged_recovery_shared import (
        write_adopted_locked,
        write_held_locked,
    )
    from sase.agent.staged_handoff import acquire_adoption_lock

    artifacts, checkout, project_file, claim = origin
    (checkout / "tracked.txt").write_text("held\n")
    recover_staged_handoff(str(artifacts), mode="explicit")
    held = read_workspace_retention_record(artifacts)
    assert held is not None and held.unresolved is True

    successor = replace(claim, pid=123456, artifacts_timestamp="20261120120000")
    write_project_file("proj", workspace_dir=str(checkout), running_claims=[successor])
    with acquire_adoption_lock(artifacts):
        write_adopted_locked(staged_id=STAGED_ID, refs={}, artifacts_dir=str(artifacts))
        write_held_locked(STAGED_ID, "late refusal", artifacts_dir=str(artifacts))

    settled = read_workspace_retention_record(artifacts)
    assert settled is not None
    assert settled.unresolved is False
    assert settled.payload.get("settled_reason") == "staged_readopt"
    assert get_claimed_workspaces(project_file) == [successor]
    assert (checkout / "tracked.txt").read_text() == "held\n"
    assert read_adoption_receipt(str(artifacts))["outcome"] == "adopted"


def test_degraded_adoption_leaves_origin_hold_unresolved(origin):
    """A successor that does not take the origin claim leaves the hold open."""
    from sase.axe._run_agent_exec_staged_recovery_shared import write_adopted_locked
    from sase.agent.staged_handoff import acquire_adoption_lock

    artifacts, checkout, project_file, claim = origin
    (checkout / "tracked.txt").write_text("held\n")
    recover_staged_handoff(str(artifacts), mode="explicit")
    with acquire_adoption_lock(artifacts):
        write_adopted_locked(staged_id=STAGED_ID, refs={}, artifacts_dir=str(artifacts))

    record = read_workspace_retention_record(artifacts)
    assert record is not None and record.unresolved is True
    remaining = get_claimed_workspaces(project_file)
    assert len(remaining) == 1
    assert remaining[0].pid == claim.pid
    assert remaining[0].artifacts_timestamp == claim.artifacts_timestamp
    assert remaining[0].pinned is True
    assert (checkout / "tracked.txt").read_text() == "held\n"
