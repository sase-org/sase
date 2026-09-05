"""Capture, reconcile, and prune behavior of the incoming-cache pass."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import incoming_cache
from sase.agents_sync.git_objects import LocalGitObjectReader
from sase.agents_sync.incoming_detection import (
    IncomingCaptureProgress,
    capture_fetched_agent_updates,
)

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
    pending, diagnostics = incoming_cache.reconcile_pending_items(
        current.pending_updates,
        project_key=current.project_key,
        owner=LOCAL_OWNER,
        owner_v2_hoods=current.owner_v2_hoods,
    )
    assert pending == current.pending_updates
    assert diagnostics == ()


def test_refresh_uses_one_cat_file_session_for_fetched_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _seed = setup_v2_remote(tmp_path)
    patch_target(monkeypatch, target)
    popen = subprocess.Popen
    cat_file_invocations: list[tuple[str, ...]] = []

    def counting_popen(
        args: object,
        *popen_args: object,
        **popen_kwargs: object,
    ) -> subprocess.Popen[str]:
        argv = tuple(str(arg) for arg in args) if isinstance(args, list) else ()
        if "cat-file" in argv:
            cat_file_invocations.append(argv)
        return popen(args, *popen_args, **popen_kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "Popen", counting_popen)

    current = refresh(target, network_calls=[], now=100.0).projects[0]

    assert current.validated_foreign_count == 2
    assert len(cat_file_invocations) == 1
    assert cat_file_invocations[0][-3:] == ("cat-file", "--batch", "-Z")


def test_capture_reports_manifest_and_hood_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _seed = setup_v2_remote(tmp_path)
    events: list[IncomingCaptureProgress] = []

    report = capture_fetched_agent_updates(
        target,
        LOCAL_OWNER,
        reader=LocalGitObjectReader(target.sidecar_path),
        now=100.0,
        progress_callback=events.append,
    )

    assert report is not None
    assert events[0] == IncomingCaptureProgress("owner_manifests", 0, 3)
    assert IncomingCaptureProgress("hoods", 0, 3) in events
    assert events[-1] == IncomingCaptureProgress("hoods", 3, 3, "bob.athena.crew")


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


def test_refresh_clears_stale_quarantine_after_sidecar_bytes_match_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, seed = setup_v2_remote(tmp_path)
    patch_target(monkeypatch, target)
    chat_path = seed / "agents" / "bob.athena.crew--code" / "chat.md"
    relative = chat_path.relative_to(seed).as_posix()
    git(seed, "rm", relative)
    commit_and_push(seed, "drop referenced payload")

    first = refresh(target, network_calls=[], now=100.0).projects[0]

    assert any("bob.athena.crew" in row for row in first.quarantine_diagnostics)
    git(seed, "checkout", "HEAD~1", "--", relative)
    commit_and_push(seed, "restore referenced payload")
    second = refresh(target, network_calls=[], now=200.0).projects[0]

    assert not any("bob.athena.crew" in row for row in second.quarantine_diagnostics)
    assert {
        (item.source_username, item.source_machine) for item in second.pending_updates
    } == {("alice", "zeus"), ("bob", "athena")}


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

    still_foreign, diagnostics = incoming_cache.reconcile_pending_items(
        current.pending_updates,
        project_key=current.project_key,
        owner=LOCAL_OWNER,
        owner_v2_hoods=(),
    )
    assert any(item.cache_id == legacy.cache_id for item in still_foreign)
    assert diagnostics == ()
    assert object_path.is_dir()

    reconciled, diagnostics = incoming_cache.reconcile_pending_items(
        still_foreign,
        project_key=current.project_key,
        owner=LOCAL_OWNER,
        owner_v2_hoods=("legacy",),
    )
    repeated, repeated_diagnostics = incoming_cache.reconcile_pending_items(
        reconciled,
        project_key=current.project_key,
        owner=LOCAL_OWNER,
        owner_v2_hoods=("legacy",),
    )

    assert all(item.format_version == 2 for item in reconciled)
    assert repeated == reconciled
    assert diagnostics == ()
    assert repeated_diagnostics == ()
    assert not object_path.exists()


def test_owner_v2_manifest_extra_key_prevents_same_machine_v1_pending_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, seed = setup_v2_remote(tmp_path)
    local_manifest = seed / "users" / "alice" / "machines" / "athena" / "manifest.json"
    owner_manifest = json.loads(local_manifest.read_text(encoding="utf-8"))
    owner_manifest["compatibility_aliases"] = []
    local_manifest.write_text(json.dumps(owner_manifest), encoding="utf-8")
    write_legacy_group(seed, machine="athena", hood="crew")
    commit_and_push(seed, "add owner legacy residue with forward v2 manifest key")
    patch_target(monkeypatch, target)

    current = refresh(target, network_calls=[], now=100.0).projects[0]

    assert "crew" in current.owner_v2_hoods
    assert current.exact_owner_count == 2
    assert all(item.format_version == 2 for item in current.pending_updates)
    assert not any(
        "quarantined v2 owner manifest" in row for row in current.quarantine_diagnostics
    )


def test_refresh_prunes_owner_v1_objects_after_owner_v2_coverage(
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

    publish_owner(seed_target_for(target, seed), LOCAL_OWNER, suffix="5", hood="legacy")
    commit_and_push(seed, "publish v2 owner coverage")

    current = refresh(target, network_calls=[], now=200.0).projects[0]

    assert all(item.cache_id != legacy.cache_id for item in current.pending_updates)
    assert "legacy" in current.owner_v2_hoods
    assert not object_path.exists()
