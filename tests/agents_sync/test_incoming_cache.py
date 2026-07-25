"""Capture, reconcile, and prune behavior of the incoming-cache status pass."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import incoming_cache, status
from sase.core.agent_identity_facade import AgentOwnerIdentity

from tests.agents_sync.incoming_cache_fixtures import (
    LOCAL_OWNER,
    commit_and_push,
    git,
    patch_target,
    publish_owner,
    refresh,
    seed_target_for,
    setup_v2_remote,
    write_legacy_group,
)


def test_refresh_captures_only_foreign_hoods_without_checkout_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _seed = setup_v2_remote(tmp_path)
    patch_target(monkeypatch, target)
    before_head = git(target.sidecar_path, "rev-parse", "HEAD").stdout
    before_status = git(target.sidecar_path, "status", "--porcelain=v1").stdout
    network_calls: list[str] = []

    snapshot = refresh(target, network_calls=network_calls, now=100.0)

    current = snapshot.projects[0]
    assert network_calls == ["agents_sync.status_fetch"]
    assert current.exact_owner_count == 1
    assert current.validated_foreign_count == 2
    assert current.pending_foreign_count == 2
    assert {
        (item.source_username, item.source_machine) for item in current.pending_updates
    } == {("alice", "zeus"), ("bob", "athena")}
    assert all(
        incoming_cache.load_validated_cache_item(item).v2_package is not None
        for item in current.pending_updates
    )
    assert git(target.sidecar_path, "rev-parse", "HEAD").stdout == before_head
    assert git(target.sidecar_path, "status", "--porcelain=v1").stdout == before_status
    metadata = (
        tmp_path
        / "state"
        / "agents_sync"
        / "cache"
        / "objects"
        / current.pending_updates[0].cache_id
        / "metadata.json"
    )
    original_metadata = metadata.read_bytes()
    original_mtime = metadata.stat().st_mtime_ns
    repeated = refresh(target, network_calls=[], now=100.5)
    assert repeated.projects[0].pending_updates == current.pending_updates
    assert metadata.read_bytes() == original_metadata
    assert metadata.stat().st_mtime_ns == original_mtime

    def no_git(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"short status must not run Git: {args}")

    short = status.get_agents_sync_status(now=101.0, git_runner=no_git)
    assert short.projects[0].pending_updates == current.pending_updates


def test_corrupt_foreign_hood_does_not_suppress_other_owners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, seed = setup_v2_remote(tmp_path)
    patch_target(monkeypatch, target)
    corrupt = (
        seed
        / "users"
        / "bob"
        / "machines"
        / "athena"
        / "hoods"
        / "crew"
        / "snapshot.json"
    )
    corrupt.write_text("{}\n", encoding="utf-8")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "corrupt one owner")
    git(seed, "push")

    current = refresh(target, network_calls=[], now=100.0).projects[0]

    assert [
        (item.source_username, item.source_machine) for item in current.pending_updates
    ] == [("alice", "zeus")]
    assert any("bob.athena.crew" in row for row in current.quarantine_diagnostics)


def test_cached_reconcile_drops_owner_covered_v1_without_git_and_prunes_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, seed = setup_v2_remote(tmp_path)
    write_legacy_group(seed, machine="athena", hood="legacy")
    commit_and_push(seed, "add stale pending legacy owner hood")
    patch_target(monkeypatch, target)
    current = refresh(target, network_calls=[], now=100.0).projects[0]
    legacy = next(item for item in current.pending_updates if item.format_version == 1)
    object_path = (
        tmp_path / "state" / "agents_sync" / "cache" / "objects" / legacy.cache_id
    )
    assert object_path.is_dir()

    def no_git(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"cached reconcile must not run Git: {args}")

    wrong_owner = replace(
        current,
        owner_v2_hoods=("legacy",),
        owner_v2_identity=AgentOwnerIdentity("bob", "athena"),
    )
    status._write_agents_sync_status_snapshot(
        status.SyncStatusSnapshot(100.0, (wrong_owner,))
    )
    still_foreign = status.get_agents_sync_status(now=100.5, git_runner=no_git)
    assert any(
        item.cache_id == legacy.cache_id
        for item in still_foreign.projects[0].pending_updates
    )
    assert object_path.is_dir()

    persisted = replace(
        still_foreign.projects[0],
        owner_v2_hoods=("legacy",),
        owner_v2_identity=LOCAL_OWNER,
    )
    status._write_agents_sync_status_snapshot(
        status.SyncStatusSnapshot(100.5, (persisted,))
    )
    reconciled = status.get_agents_sync_status(now=101.0, git_runner=no_git)
    repeated = status.get_agents_sync_status(now=102.0, git_runner=no_git)

    assert all(
        item.format_version == 2 for item in reconciled.projects[0].pending_updates
    )
    assert (
        repeated.projects[0].pending_updates == reconciled.projects[0].pending_updates
    )
    assert not object_path.exists()


def test_refresh_prunes_owner_v1_objects_after_old_status_schema_is_discarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, seed = setup_v2_remote(tmp_path)
    write_legacy_group(seed, machine="athena", hood="legacy")
    commit_and_push(seed, "add legacy owner residue")
    patch_target(monkeypatch, target)
    first = refresh(target, network_calls=[], now=100.0).projects[0]
    legacy = next(item for item in first.pending_updates if item.format_version == 1)
    object_path = (
        tmp_path / "state" / "agents_sync" / "cache" / "objects" / legacy.cache_id
    )
    snapshot_path = tmp_path / "state" / "agents_sync" / "status_snapshot.json"
    stale_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    stale_snapshot["schema_version"] = status.STATUS_SCHEMA_VERSION - 1
    snapshot_path.write_text(json.dumps(stale_snapshot), encoding="utf-8")

    publish_owner(seed_target_for(target, seed), LOCAL_OWNER, suffix="5", hood="legacy")
    commit_and_push(seed, "publish v2 owner coverage")

    current = refresh(target, network_calls=[], now=200.0).projects[0]

    assert all(item.cache_id != legacy.cache_id for item in current.pending_updates)
    assert "legacy" in current.owner_v2_hoods
    assert not object_path.exists()
