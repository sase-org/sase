from __future__ import annotations

from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import incoming_cache, incoming_integration, status
from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.io import compute_bundle_digest, write_bundle, write_manifest
from sase.agents_sync.models import (
    AgentBundle,
    AgentsManifest,
    CommitRecord,
    IntegrationCounts,
    ManifestEntry,
    PortableAgentMetadata,
    ProjectTarget,
    TargetSelection,
)
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity

PROJECT = V2ProjectIdentity("proj", "Project")
LOCAL_OWNER = AgentOwnerIdentity("alice", "athena")
FOREIGN_OWNERS = (
    AgentOwnerIdentity("alice", "zeus"),
    AgentOwnerIdentity("bob", "athena"),
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _run(
    owner: AgentOwnerIdentity,
    *,
    suffix: str,
    chat: bytes = b"chat\n",
) -> InventoryRun:
    name = "crew--code"
    return InventoryRun(
        f"run-{owner.username}-{owner.machine_name}-{suffix}",
        name,
        f"{owner.username}.{owner.machine_name}.{name}",
        "completed",
        "2026-07-24T12:00:00+00:00",
        "2026-07-24T12:01:00+00:00",
        None,
        (("model", "gpt-test"),),
        (CommitRecord((suffix * 40)[:40], name, 1),),
        b"prompt\n",
        chat,
        "crew",
        None,
        (),
        f"2026072412000{suffix[0]}",
        None,
        None,
    )


def _publish_owner(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    suffix: str,
    chat: bytes = b"chat\n",
) -> None:
    publish_agent_hood(
        target,
        target.sidecar_path,
        "crew--code",
        identity=AgentIdentitySnapshot(owner),
        inventory=ProjectHoodInventory(
            owner,
            PROJECT.key,
            (_run(owner, suffix=suffix, chat=chat),),
        ),
    )


def _setup_v2_remote(tmp_path: Path) -> tuple[ProjectTarget, Path]:
    primary = tmp_path / "primary"
    primary.mkdir()
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    seed = tmp_path / "seed"
    seed.mkdir()
    seed_target = ProjectTarget(
        PROJECT.key,
        PROJECT.name,
        primary,
        (primary.resolve(),),
        seed,
        str(remote),
    )
    for index, owner in enumerate((LOCAL_OWNER, *FOREIGN_OWNERS), start=1):
        _publish_owner(seed_target, owner, suffix=str(index))
    _git(seed, "init")
    _git(seed, "config", "user.name", "Tests")
    _git(seed, "config", "user.email", "tests@example.test")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "publish hoods")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "HEAD")
    sidecar = tmp_path / "sidecar"
    _git(tmp_path, "clone", str(remote), str(sidecar))
    return (
        ProjectTarget(
            PROJECT.key,
            PROJECT.name,
            primary,
            (primary.resolve(),),
            sidecar,
            str(remote),
        ),
        seed,
    )


def _patch_target(
    monkeypatch: pytest.MonkeyPatch,
    target: ProjectTarget,
) -> None:
    selection = TargetSelection((target,), ())
    monkeypatch.setattr(status, "resolve_sync_targets", lambda _projects: selection)
    monkeypatch.setattr(
        status,
        "require_agent_owner_identity",
        lambda: LOCAL_OWNER,
    )
    monkeypatch.setattr(
        incoming_integration,
        "resolve_sync_targets",
        lambda _projects: selection,
    )
    monkeypatch.setattr(
        incoming_integration,
        "require_agent_owner_identity",
        lambda: LOCAL_OWNER,
    )


def _refresh(
    target: ProjectTarget,
    *,
    network_calls: list[str],
    now: float,
) -> status.SyncStatusSnapshot:
    def runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        if network:
            network_calls.append(op)
        return run_git(cwd, args, network=network, op=op)

    return status.get_agents_sync_status(
        refresh=True,
        now=now,
        git_runner=runner,
    )


def test_refresh_captures_only_foreign_hoods_without_checkout_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _seed = _setup_v2_remote(tmp_path)
    _patch_target(monkeypatch, target)
    before_head = _git(target.sidecar_path, "rev-parse", "HEAD").stdout
    before_status = _git(target.sidecar_path, "status", "--porcelain=v1").stdout
    network_calls: list[str] = []

    snapshot = _refresh(target, network_calls=network_calls, now=100.0)

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
    assert _git(target.sidecar_path, "rev-parse", "HEAD").stdout == before_head
    assert _git(target.sidecar_path, "status", "--porcelain=v1").stdout == before_status
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
    repeated = _refresh(target, network_calls=[], now=100.5)
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


def test_cached_integration_is_no_network_and_receipted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _seed = _setup_v2_remote(tmp_path)
    _patch_target(monkeypatch, target)
    snapshot = _refresh(target, network_calls=[], now=100.0)
    item = snapshot.projects[0].pending_updates[0]
    monkeypatch.setattr(
        incoming_integration,
        "integrate_v2_hoods",
        lambda *_args, **_kwargs: IntegrationCounts(
            hoods_imported=1,
            runs_imported=1,
        ),
    )
    network_calls: list[str] = []

    def local_only_runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        assert not network
        network_calls.append(op)
        return run_git(cwd, args, network=False, op=op)

    first = incoming_integration.integrate_cached_agent_updates(
        (item,),
        git_runner=local_only_runner,
    )
    second = incoming_integration.integrate_cached_agent_updates(
        (item,),
        git_runner=local_only_runner,
    )

    assert first[0].disposition == "applied"
    assert first[0].hoods_imported == 1
    assert second[0].disposition == "already_applied"
    assert network_calls and all("fetch" not in op for op in network_calls)
    receipt = incoming_cache.read_project_receipts(PROJECT.key)[0]
    assert receipt.hood_digest == item.hood_digest
    assert status.get_agents_sync_status().projects[0].pending_foreign_count == 1


def test_corrupt_foreign_hood_does_not_suppress_other_owners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, seed = _setup_v2_remote(tmp_path)
    _patch_target(monkeypatch, target)
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
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "corrupt one owner")
    _git(seed, "push")

    current = _refresh(target, network_calls=[], now=100.0).projects[0]

    assert [
        (item.source_username, item.source_machine) for item in current.pending_updates
    ] == [("alice", "zeus")]
    assert any("bob.athena.crew" in row for row in current.quarantine_diagnostics)


def test_full_sync_import_pass_advances_foreign_receipts_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _seed = _setup_v2_remote(tmp_path)
    _patch_target(monkeypatch, target)
    current = _refresh(target, network_calls=[], now=100.0).projects[0]
    monkeypatch.setattr(
        incoming_integration,
        "integrate_v2_hoods",
        lambda *_args, **_kwargs: IntegrationCounts(hoods_imported=1),
    )

    counts = incoming_integration.integrate_agent_imports_with_receipts(
        target,
        target.sidecar_path,
        LOCAL_OWNER,
    )

    receipts = incoming_cache.read_project_receipts(PROJECT.key)
    assert counts.hoods_imported == 3
    assert {
        (receipt.source_username, receipt.source_machine) for receipt in receipts
    } == {("alice", "zeus"), ("bob", "athena")}
    assert all(
        receipt.hood_digest in {item.hood_digest for item in current.pending_updates}
        for receipt in receipts
    )
    assert status.get_agents_sync_status().projects[0].pending_foreign_count == 0


def test_cached_integration_reports_stale_missing_quarantine_and_lock_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _seed = _setup_v2_remote(tmp_path)
    _patch_target(monkeypatch, target)
    items = _refresh(target, network_calls=[], now=100.0).projects[0].pending_updates
    stale_item, corrupt_item = items
    newer_digest = "f" * 64
    newer_id = incoming_cache._cache_id_for(
        project_key=stale_item.project_key,
        project=stale_item.project,
        format_version=stale_item.format_version,
        source_owner_kind=stale_item.source_owner_kind,
        source_username=stale_item.source_username,
        source_machine=stale_item.source_machine,
        top_hood=stale_item.top_hood,
        hood_digest=newer_digest,
    )
    newer = replace(
        stale_item,
        cache_id=newer_id,
        hood_digest=newer_digest,
        cache_created_at=200.0,
    )
    incoming_cache.write_import_receipt(
        incoming_cache.receipt_for_item(newer, applied_at=201.0)
    )
    stale = incoming_integration.integrate_cached_agent_updates((stale_item,))
    assert stale[0].disposition == "stale"

    missing = replace(
        corrupt_item,
        top_hood="missing",
        hood_digest="e" * 64,
        cache_id=incoming_cache._cache_id_for(
            project_key=corrupt_item.project_key,
            project=corrupt_item.project,
            format_version=corrupt_item.format_version,
            source_owner_kind=corrupt_item.source_owner_kind,
            source_username=corrupt_item.source_username,
            source_machine=corrupt_item.source_machine,
            top_hood="missing",
            hood_digest="e" * 64,
        ),
    )
    assert (
        incoming_integration.integrate_cached_agent_updates((missing,))[0].disposition
        == "missing"
    )

    loaded = incoming_cache.load_validated_cache_item(corrupt_item)
    snapshot_path = next(loaded.payload_root.rglob("snapshot.json"))
    snapshot_path.write_text("{}", encoding="utf-8")
    quarantined = incoming_integration.integrate_cached_agent_updates((corrupt_item,))
    assert quarantined[0].disposition == "quarantined"

    lock_path = target.sidecar_path / ".git" / "sase-agents-sync.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        busy = incoming_integration.integrate_cached_agent_updates(
            (missing,),
            lock_timeout_seconds=0,
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    assert busy[0].disposition == "failed"
    assert "lock is busy" in busy[0].diagnostics[0]


def test_captured_sha_a_remains_integrable_after_newer_b_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, seed = _setup_v2_remote(tmp_path)
    _patch_target(monkeypatch, target)
    first = _refresh(target, network_calls=[], now=100.0)
    item_a = next(
        item
        for item in first.projects[0].pending_updates
        if item.source_username == "bob"
    )
    seed_target = ProjectTarget(
        PROJECT.key,
        PROJECT.name,
        target.primary_checkout,
        target.primary_roots,
        seed,
        target.remote_url,
    )
    _publish_owner(
        seed_target,
        AgentOwnerIdentity("bob", "athena"),
        suffix="4",
        chat=b"new chat\n",
    )
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "refresh bob hood")
    _git(seed, "push")
    second = _refresh(target, network_calls=[], now=200.0)
    item_b = next(
        item
        for item in second.projects[0].pending_updates
        if item.source_username == "bob"
    )
    assert item_b.hood_digest != item_a.hood_digest
    monkeypatch.setattr(
        incoming_integration,
        "integrate_v2_hoods",
        lambda *_args, **_kwargs: IntegrationCounts(hoods_imported=1),
    )

    def no_network_runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        assert not network
        return run_git(cwd, args, network=False, op=op)

    outcome = incoming_integration.integrate_cached_agent_updates(
        (item_a,),
        git_runner=no_network_runner,
    )
    after = status.get_agents_sync_status(now=201.0)

    assert outcome[0].disposition == "applied"
    assert any(
        item.cache_id == item_b.cache_id for item in after.projects[0].pending_updates
    )


def test_username_unknown_v1_entries_are_grouped_by_machine_and_hood(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    primary = tmp_path / "primary"
    primary.mkdir()
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    seed = tmp_path / "seed"
    seed.mkdir()
    entries: list[ManifestEntry] = []
    for index, role in enumerate(("plan", "code"), start=1):
        name = f"zeus.crew--{role}"
        metadata = PortableAgentMetadata(
            name,
            "zeus",
            f"2026072412000{index}",
            2,
        )
        commits = (CommitRecord(str(index) * 40, role, index),)
        chat = f"{role}\n".encode()
        digest = compute_bundle_digest(metadata, commits, chat)
        bundle = AgentBundle(metadata, commits, chat, digest)
        write_bundle(seed, bundle)
        entries.append(
            ManifestEntry(
                name,
                "zeus",
                digest,
                metadata.artifact_timestamp,
                "2026-07-24T12:00:00+00:00",
            )
        )
    write_manifest(seed / "manifest.json", AgentsManifest(tuple(entries)))
    _git(seed, "init")
    _git(seed, "config", "user.name", "Tests")
    _git(seed, "config", "user.email", "tests@example.test")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "legacy")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "HEAD")
    sidecar = tmp_path / "sidecar"
    _git(tmp_path, "clone", str(remote), str(sidecar))
    target = ProjectTarget(
        PROJECT.key,
        PROJECT.name,
        primary,
        (primary.resolve(),),
        sidecar,
        str(remote),
    )
    _patch_target(monkeypatch, target)

    current = _refresh(target, network_calls=[], now=100.0).projects[0]

    assert current.pending_foreign_count == 1
    item = current.pending_updates[0]
    assert item.format_version == 1
    assert item.source_username is None
    assert item.source_machine == "zeus"
    assert item.top_hood == "crew"
    assert item.run_count == 2
    assert incoming_cache.load_validated_cache_item(item).legacy_manifest is not None
