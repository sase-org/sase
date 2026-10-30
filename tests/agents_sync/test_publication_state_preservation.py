"""Terminal-state preservation across targeted and full publication."""

from __future__ import annotations

import json
from pathlib import Path

from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.inventory_sources import _artifact_state
from sase.agents_sync.publication import publish_agent_hood, reconcile_agent_hoods
from sase.agents_sync.publication_validation import read_hood_snapshot
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)
from tests.agents_sync.publication_fixtures import _identity, _inventory, _target


def _record(
    *,
    waiting: bool = False,
    pending_question: bool = False,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/tmp/proj",
        project_file="/tmp/proj/proj.sase",
        workflow_dir_name="ace-run",
        artifact_dir="/tmp/artifact",
        timestamp="20260723120000",
        waiting=WaitingMarkerWire(waiting_for=["foo.peer"]) if waiting else None,
        pending_question=(
            PendingQuestionMarkerWire(submitted_at="2026-07-23T12:00:00+00:00")
            if pending_question
            else None
        ),
    )


def test_stale_waiting_metadata_does_not_mask_done_marker() -> None:
    done = {
        "outcome": "completed",
        "finished_at": "2026-07-23T12:01:00+00:00",
    }
    assert _artifact_state(_record(waiting=True), done) == "completed"
    assert _artifact_state(_record(pending_question=True), done) == "completed"
    assert _artifact_state(_record(waiting=True, pending_question=True), done) == (
        "completed"
    )


def test_stale_pending_question_does_not_mask_failed_marker() -> None:
    done = {
        "outcome": "failed",
        "finished_at": "2026-07-23T12:01:00+00:00",
    }
    assert _artifact_state(_record(waiting=True), done) == "failed"


def test_live_evidence_stays_live_without_done_marker() -> None:
    assert _artifact_state(_record(waiting=True), None) == "waiting"
    assert _artifact_state(_record(pending_question=True), None) == "waiting"
    assert _artifact_state(_record(), None) == "active"


def _run_by_global(inventory: ProjectHoodInventory, global_name: str) -> InventoryRun:
    for run in inventory.runs:
        if run.global_name == global_name:
            return run
    raise AssertionError(f"missing run {global_name}")


def _snapshot_state(repo: Path, hood: str) -> dict[str, str]:
    snapshot = read_hood_snapshot(
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / hood
        / "snapshot.json"
    )
    return {run.global_name: run.state for run in snapshot.runs}


def _snapshot_bytes(repo: Path, hood: str) -> bytes:
    return (
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / hood
        / "snapshot.json"
    ).read_bytes()


def test_targeted_publication_preserves_terminal_against_stale_active(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    publish_agent_hood(
        target, repo, "foo.bar.baz--code", identity=_identity(), inventory=inventory
    )
    before = _snapshot_bytes(repo, "foo")
    terminal_states = _snapshot_state(repo, "foo")
    target_global = "alice.athena.foo.bar.baz--plan"
    assert terminal_states[target_global] == "completed"

    stale = _run_by_global(inventory, target_global)
    stale_active = InventoryRun(
        stale.source_run_id,
        stale.local_name,
        stale.global_name,
        "active",
        stale.started_at,
        None,
        None,
        stale.metadata,
        stale.commits,
        stale.prompt_bytes,
        stale.chat_bytes,
        stale.agent_session_name,
        stale.clan_name,
        stale.relationships,
        stale.timestamp,
        stale.embedded_workflows_bytes,
        stale.prompt_steps_bytes,
        stale.source_label,
    )
    stale_inventory = ProjectHoodInventory(
        inventory.owner,
        inventory.project_key,
        tuple(
            stale_active if run.global_name == target_global else run
            for run in inventory.runs
        ),
    )
    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=stale_inventory,
    )
    after_states = _snapshot_state(repo, "foo")
    assert after_states[target_global] == "completed"
    assert _snapshot_bytes(repo, "foo") == before
    # The preserved terminal snapshot keeps its state payload bytes stable.
    state_path = repo / "agents" / f"{target_global}" / "state.json"
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["state"] == "completed"


def test_full_reconciliation_preserves_terminal_and_repeats_identically(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    owner = AgentOwnerIdentity("alice", "athena")
    inventory = _inventory(owner)
    reconcile_agent_hoods(target, repo, identity=_identity(), inventory=inventory)
    first = _snapshot_bytes(repo, "foo")

    # Repeating the unchanged input writes identical snapshot bytes.
    reconcile_agent_hoods(target, repo, identity=_identity(), inventory=inventory)
    assert _snapshot_bytes(repo, "foo") == first


def test_different_run_identity_never_borrows_terminal(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    publish_agent_hood(
        target, repo, "foo.bar.baz--code", identity=_identity(), inventory=inventory
    )
    target_global = "alice.athena.foo.bar.baz--plan"
    assert _snapshot_state(repo, "foo")[target_global] == "completed"

    stale = _run_by_global(inventory, target_global)
    reused = InventoryRun(
        "run-different-identity",
        stale.local_name,
        stale.global_name,
        "active",
        stale.started_at,
        None,
        None,
        stale.metadata,
        stale.commits,
        stale.prompt_bytes,
        stale.chat_bytes,
        stale.agent_session_name,
        stale.clan_name,
        stale.relationships,
        stale.timestamp,
        stale.embedded_workflows_bytes,
        stale.prompt_steps_bytes,
        stale.source_label,
    )
    reused_inventory = ProjectHoodInventory(
        inventory.owner,
        inventory.project_key,
        tuple(
            reused if run.global_name == target_global else run
            for run in inventory.runs
        ),
    )
    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=reused_inventory,
    )
    # A reused name with a different run identity publishes its own live state.
    assert _snapshot_state(repo, "foo")[target_global] == "active"


def test_live_runs_stay_live_and_foreign_owners_survive(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    publish_agent_hood(
        target, repo, "foo.bar.baz--code", identity=_identity(), inventory=inventory
    )
    live_global = "alice.athena.foo.boom"
    assert _snapshot_state(repo, "foo")[live_global] == "waiting"

    # Republishing the same live inventory keeps live runs live.
    publish_agent_hood(
        target, repo, "foo.bar.baz--code", identity=_identity(), inventory=inventory
    )
    assert _snapshot_state(repo, "foo")[live_global] == "waiting"

    # A foreign owner publishes into its own manifest without disturbing alice.
    bob_owner = AgentOwnerIdentity("bob", "zeus")
    bob_run = InventoryRun(
        "run-bob",
        "other",
        "bob.zeus.other",
        "completed",
        None,
        None,
        None,
        (),
        (),
        b"other\n",
        b"chat\n",
        None,
        None,
        (),
        "20260723130000",
    )
    reconcile_agent_hoods(
        target,
        repo,
        identity=AgentIdentitySnapshot(bob_owner),
        inventory=ProjectHoodInventory(bob_owner, "proj", (bob_run,)),
    )
    assert _snapshot_state(repo, "foo")[live_global] == "waiting"
    assert (repo / "users" / "bob" / "machines" / "zeus" / "manifest.json").is_file()
