from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.publication import publish_agent_hood, reconcile_agent_hoods
from sase.agents_sync.publication_validation import load_validated_publication
from sase.agents_sync.v2_io import content_digest, v2_json_bytes
from sase.agents_sync.v2_models import V2HoodSnapshot
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_session_manifest import (
    SESSION_MANIFEST_CLASS_CURRENT,
    SESSION_MANIFEST_CLASS_SUPPORTED_LEGACY,
    classify_session_manifest_files,
)
from tests.agents_sync.publication_fixtures import _identity, _inventory, _target


def _owner_manifest_path(repo: Path) -> Path:
    return repo / "users" / "alice" / "machines" / "athena" / "manifest.json"


def _canonical_files(snapshot: V2HoodSnapshot) -> tuple[str, ...]:
    """Derive *snapshot*'s canonical explicit file set through the Rust core."""
    decision = classify_session_manifest_files(
        owner_username=snapshot.owner.username,
        owner_machine=snapshot.owner.machine_name,
        local_hood=snapshot.local_hood,
        run_global_names=tuple(run.global_name for run in snapshot.runs),
        run_file_paths=tuple(
            reference.path for run in snapshot.runs for _kind, reference in run.files
        ),
        containers=tuple(
            (container.kind, container.global_name) for container in snapshot.containers
        ),
        explicit_files=None,
    )
    return decision.canonical_files


def test_publication_skips_undecodable_foreign_manifest_but_keeps_local_strict(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    foreign_manifest = repo / "users" / "bob" / "machines" / "zeus" / "manifest.json"
    foreign_manifest.parent.mkdir(parents=True)
    foreign_manifest.write_text("{}\n", encoding="utf-8")

    counts = publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )

    assert counts.hoods_unchanged == 1
    assert any(
        "users/bob/machines/zeus/manifest.json: skipped v2 owner manifest" in row
        for row in counts.diagnostics
    )

    local_manifest = repo / "users" / "alice" / "machines" / "athena" / "manifest.json"
    local_manifest.write_text("{}\n", encoding="utf-8")
    with pytest.raises(AgentsSyncFormatError, match="missing required keys"):
        publish_agent_hood(
            target,
            repo,
            "foo.bar.baz--code",
            identity=_identity(),
            inventory=inventory,
        )


def test_plan_hoods_refuses_to_republish_from_an_empty_manifest(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    _owner_manifest_path(repo).unlink()

    with pytest.raises(AgentsSyncFormatError, match="on-disk hood director"):
        publish_agent_hood(
            target,
            repo,
            "foo.bar.baz--code",
            identity=_identity(),
            inventory=inventory,
        )


def test_plan_hoods_diagnoses_but_still_publishes_when_manifest_omits_a_hood(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    counts = reconcile_agent_hoods(
        target,
        repo,
        identity=_identity(),
        inventory=inventory,
    )
    assert counts.hoods_published == 2

    manifest_path = _owner_manifest_path(repo)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["hoods"]["work"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    refreshed = publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )

    assert any(
        "omits" in diagnostic and "work" in diagnostic
        for diagnostic in refreshed.diagnostics
    )
    assert (
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "work"
        / "snapshot.json"
    ).is_file()


def test_plan_hoods_manifest_guard_is_inert_on_a_clean_repository(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))

    counts = publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )

    assert counts.hoods_published == 1
    assert not any("omits" in diagnostic for diagnostic in counts.diagnostics)


def test_manifest_writer_omits_explicit_file_lists(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))

    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    slim_manifest = json.loads(_owner_manifest_path(repo).read_text(encoding="utf-8"))
    assert "files" not in slim_manifest["hoods"]["foo"]

    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    resumed_manifest = json.loads(
        _owner_manifest_path(repo).read_text(encoding="utf-8")
    )
    assert "files" not in resumed_manifest["hoods"]["foo"]


def test_plan_hoods_write_guard_rejects_a_manifest_over_the_read_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import v2_manifest_io

    monkeypatch.setattr(v2_manifest_io, "MAX_MANIFEST_HOODS", 0)
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))

    with pytest.raises(AgentsSyncFormatError, match="hood read cap"):
        publish_agent_hood(
            target,
            repo,
            "foo.bar.baz--code",
            identity=_identity(),
            inventory=inventory,
        )

    assert not _owner_manifest_path(repo).exists()


def _publish_foo_with_explicit_files(target, repo, inventory):
    """Publish hood ``foo`` slim, then attach its canonical file list on disk.

    Writers no longer emit explicit ``files`` lists, but old manifests still
    carry them, so compat scenarios synthesize one via :func:`_canonical_files`.
    """
    from sase.agents_sync.v2_io import read_hood_snapshot

    counts = publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    assert counts.hoods_published == 1
    snapshot = read_hood_snapshot(
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    )
    manifest_path = _owner_manifest_path(repo)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["hoods"]["foo"]["files"] = list(_canonical_files(snapshot))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return counts


def _to_legacy_family_only(files: list[str]) -> list[str]:
    assert any(path.startswith("sessions/") for path in files)
    legacy = [path for path in files if not path.startswith("sessions/")]
    assert any(path.startswith("families/") for path in legacy)
    return sorted(legacy)


def _bob_inventory():
    from sase.agents_sync.inventory_models import InventoryRun, ProjectHoodInventory

    owner = AgentOwnerIdentity("bob", "zeus")
    run = InventoryRun(
        "run-bob-01",
        "solo",
        "bob.zeus.solo",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        (("model", "gpt"),),
        (),
        b"prompt for solo\n",
        b"chat\n",
        None,
        None,
        (),
        "20260723120001",
    )
    return ProjectHoodInventory(owner, "proj", (run,))


def test_legacy_family_only_manifest_accepted_for_cross_owner_publish(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    _publish_foo_with_explicit_files(target, repo, inventory)

    manifest_path = _owner_manifest_path(repo)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fat_files = manifest["hoods"]["foo"]["files"]
    assert any(path.startswith("sessions/") for path in fat_files)
    legacy_files = _to_legacy_family_only(list(fat_files))
    manifest["hoods"]["foo"]["files"] = legacy_files
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    before = {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file()
    }

    zap_counts = publish_agent_hood(
        target,
        repo,
        "zap.solo",
        identity=_identity(),
        inventory=inventory,
    )
    assert zap_counts.hoods_published == 1

    after_foo_snapshot = (
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    ).read_bytes()
    assert (
        after_foo_snapshot
        == before["users/alice/machines/athena/hoods/foo/snapshot.json"]
    )
    assert (repo / "sessions" / "alice.athena.foo.bar.baz.md").is_file()
    assert (repo / "sessions" / "alice.athena.foo.rootless.md").is_file()
    assert (repo / "families" / "alice.athena.foo.bar.baz.md").is_file()
    assert (repo / "families" / "alice.athena.foo.rootless.md").is_file()

    bob_inventory = _bob_inventory()
    bob_identity = AgentIdentitySnapshot(AgentOwnerIdentity("bob", "zeus"))
    bob_counts = publish_agent_hood(
        target,
        repo,
        "solo",
        identity=bob_identity,
        inventory=bob_inventory,
    )
    assert bob_counts.hoods_published == 1
    assert (repo / "agents" / "bob.zeus.solo" / "README.md").is_file()
    assert (
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    ).read_bytes() == after_foo_snapshot

    repeat = publish_agent_hood(
        target,
        repo,
        "zap.solo",
        identity=_identity(),
        inventory=inventory,
    )
    assert repeat.hoods_unchanged >= 1


def test_legacy_manifest_rejects_partial_and_unexpected_paths(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    _publish_foo_with_explicit_files(target, repo, inventory)

    manifest_path = _owner_manifest_path(repo)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fat_files = list(manifest["hoods"]["foo"]["files"])
    legacy_files = _to_legacy_family_only(fat_files)

    partial = sorted(legacy_files[:-1])
    manifest["hoods"]["foo"]["files"] = partial
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AgentsSyncFormatError, match="manifest file set mismatch"):
        publish_agent_hood(
            target,
            repo,
            "zap.solo",
            identity=_identity(),
            inventory=inventory,
        )

    unexpected = sorted([*legacy_files, "sessions/alice.athena.foo.bar.nonexistent.md"])
    manifest["hoods"]["foo"]["files"] = unexpected
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AgentsSyncFormatError, match="manifest file set mismatch"):
        publish_agent_hood(
            target,
            repo,
            "zap.solo",
            identity=_identity(),
            inventory=inventory,
        )


def test_no_session_hood_has_no_legacy_exception_and_slim_stays_supported(
    tmp_path: Path,
) -> None:
    from sase.agents_sync.v2_io import read_hood_snapshot

    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    publish_agent_hood(
        target,
        repo,
        "zap.solo",
        identity=_identity(),
        inventory=inventory,
    )
    manifest = json.loads(_owner_manifest_path(repo).read_text(encoding="utf-8"))
    assert "files" not in manifest["hoods"]["zap"]

    snapshot = read_hood_snapshot(
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "zap"
        / "snapshot.json"
    )
    zap_files = list(_canonical_files(snapshot))
    assert not any(path.startswith("sessions/") for path in zap_files)
    assert not any(path.startswith("families/") for path in zap_files)
    decision = classify_session_manifest_files(
        owner_username="alice",
        owner_machine="athena",
        local_hood="zap",
        run_global_names=tuple(run.global_name for run in snapshot.runs),
        run_file_paths=tuple(
            ref.path for run in snapshot.runs for _kind, ref in run.files
        ),
        containers=tuple((item.kind, item.global_name) for item in snapshot.containers),
        explicit_files=tuple(zap_files),
    )
    assert decision.classification == SESSION_MANIFEST_CLASS_CURRENT

    publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    slim_manifest = json.loads(_owner_manifest_path(repo).read_text(encoding="utf-8"))
    assert "files" not in slim_manifest["hoods"]["foo"]
    load_validated_publication(repo)


def test_genuine_corruption_still_fails_beside_legacy_support(
    tmp_path: Path,
) -> None:
    from sase.agents_sync.v2_io import read_hood_snapshot

    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    _publish_foo_with_explicit_files(target, repo, inventory)

    manifest_path = _owner_manifest_path(repo)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["hoods"]["foo"]["files"] = _to_legacy_family_only(
        list(manifest["hoods"]["foo"]["files"])
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    snapshot_path = (
        repo
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    )
    pristine_snapshot = snapshot_path.read_bytes()
    pristine_manifest = manifest_path.read_bytes()

    snapshot = read_hood_snapshot(snapshot_path)
    assert _canonical_files(snapshot) != tuple(
        json.loads(pristine_manifest)["hoods"]["foo"]["files"]
    )
    decision = classify_session_manifest_files(
        owner_username="alice",
        owner_machine="athena",
        local_hood="foo",
        run_global_names=tuple(run.global_name for run in snapshot.runs),
        run_file_paths=tuple(
            ref.path for run in snapshot.runs for _kind, ref in run.files
        ),
        containers=tuple((item.kind, item.global_name) for item in snapshot.containers),
        explicit_files=tuple(json.loads(pristine_manifest)["hoods"]["foo"]["files"]),
    )
    assert decision.classification == SESSION_MANIFEST_CLASS_SUPPORTED_LEGACY

    tampered = json.loads(pristine_snapshot.decode("utf-8"))
    tampered["owner"]["machine_name"] = "zeus"
    snapshot_path.write_bytes(v2_json_bytes(tampered))
    with pytest.raises(AgentsSyncFormatError, match="snapshot digest mismatch"):
        publish_agent_hood(
            target,
            repo,
            "zap.solo",
            identity=_identity(),
            inventory=inventory,
        )
    snapshot_path.write_bytes(pristine_snapshot)
    manifest_path.write_bytes(pristine_manifest)

    payload_path = next(
        path
        for path in sorted(
            (repo / "agents").rglob("meta.json"),
        )
    )
    payload_path.write_bytes(b'{"tampered": true}\n')
    with pytest.raises(AgentsSyncFormatError, match="file digest mismatch"):
        load_validated_publication(repo)
    assert content_digest(payload_path.read_bytes()) != content_digest(b"")
