"""Integration of cached incoming updates: receipts, dispositions, and locking."""

from __future__ import annotations

from dataclasses import replace
import fcntl
import os
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import incoming_cache, incoming_integration, status
from sase.agents_sync.git import run_git
from sase.agents_sync.models import IntegrationCounts
from sase.core.agent_identity_facade import AgentOwnerIdentity

from tests.agents_sync.incoming_cache_fixtures import (
    LOCAL_OWNER,
    PROJECT,
    git,
    patch_target,
    publish_owner,
    refresh,
    seed_target_for,
    setup_v2_remote,
)


def test_cached_integration_is_no_network_and_receipted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _seed = setup_v2_remote(tmp_path)
    patch_target(monkeypatch, target)
    snapshot = refresh(target, network_calls=[], now=100.0)
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


def test_full_sync_import_pass_advances_foreign_receipts_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _seed = setup_v2_remote(tmp_path)
    patch_target(monkeypatch, target)
    current = refresh(target, network_calls=[], now=100.0).projects[0]
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
    target, _seed = setup_v2_remote(tmp_path)
    patch_target(monkeypatch, target)
    items = refresh(target, network_calls=[], now=100.0).projects[0].pending_updates
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
    target, seed = setup_v2_remote(tmp_path)
    patch_target(monkeypatch, target)
    first = refresh(target, network_calls=[], now=100.0)
    item_a = next(
        item
        for item in first.projects[0].pending_updates
        if item.source_username == "bob"
    )
    publish_owner(
        seed_target_for(target, seed),
        AgentOwnerIdentity("bob", "athena"),
        suffix="4",
        chat=b"new chat\n",
    )
    git(seed, "add", ".")
    git(seed, "commit", "-m", "refresh bob hood")
    git(seed, "push")
    second = refresh(target, network_calls=[], now=200.0)
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
