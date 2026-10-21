from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.publication_repair import (
    repair_owner_hood_digests,
    _repair_owner_manifest,
)
from sase.agents_sync.publication_validation import load_validated_publication
from sase.agents_sync.v2_io import (
    apply_payload_atomic,
    content_digest,
    read_hood_snapshot,
    v2_json_bytes,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_session_manifest import classify_session_manifest_files
from sase.plan_chain import AGENT_SESSION_KEY


def _target(tmp_path: Path, name: str) -> ProjectTarget:
    root = tmp_path / name
    primary = root / "primary"
    primary.mkdir(parents=True)
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        root / "sidecar",
        "unused",
    )


def _run(
    owner: AgentOwnerIdentity,
    name: str,
    suffix: str,
    *,
    agent_session: str | None = None,
) -> InventoryRun:
    metadata = (("model", "gpt"),)
    if agent_session is not None:
        metadata += ((AGENT_SESSION_KEY, agent_session),)
    return InventoryRun(
        f"run-{suffix}",
        name,
        f"{owner.username}.{owner.machine_name}.{name}",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        metadata,
        (),
        f"prompt for {name}\n".encode(),
        f"chat for {name}\n".encode(),
        agent_session,
        None,
        (),
        f"20260723120{suffix}",
    )


def _publish(
    tmp_path: Path,
    slot: str,
    owner: AgentOwnerIdentity,
    name: str,
) -> tuple[ProjectTarget, Path]:
    target = _target(tmp_path, slot)
    repo = target.sidecar_path
    repo.mkdir(exist_ok=True)
    inventory = ProjectHoodInventory(owner, "proj", (_run(owner, name, "01"),))
    publish_agent_hood(
        target,
        repo,
        name,
        identity=AgentIdentitySnapshot(owner),
        inventory=inventory,
    )
    return target, repo


def _chat_path(repo: Path, owner: AgentOwnerIdentity, name: str) -> Path:
    return repo / "agents" / f"{owner.username}.{owner.machine_name}.{name}" / "chat.md"


def _manifest_path(repo: Path, owner: AgentOwnerIdentity) -> Path:
    return (
        repo
        / "users"
        / owner.username
        / "machines"
        / owner.machine_name
        / "manifest.json"
    )


def _snapshot_path(repo: Path, owner: AgentOwnerIdentity, hood: str) -> Path:
    return (
        repo
        / "users"
        / owner.username
        / "machines"
        / owner.machine_name
        / "hoods"
        / hood
        / "snapshot.json"
    )


def _canonical_files(
    repo: Path, owner: AgentOwnerIdentity, hood: str
) -> tuple[str, ...]:
    snapshot = read_hood_snapshot(_snapshot_path(repo, owner, hood))
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


def _set_explicit_files(
    repo: Path,
    owner: AgentOwnerIdentity,
    hood: str,
    files: list[str],
) -> None:
    path = _manifest_path(repo, owner)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["hoods"][hood]["files"] = files
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _stale_files(
    owner: AgentOwnerIdentity, hood: str, files: tuple[str, ...]
) -> list[str]:
    stale_path = (
        f"agents/{owner.username}.{owner.machine_name}.{hood}.retired/README.md"
    )
    return sorted([*files, stale_path])


def test_repair_resigns_drifted_payload_and_publication_recovers(
    tmp_path: Path,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, repo = _publish(tmp_path, "case1", owner, "foo")
    chat_path = _chat_path(repo, owner, "foo")

    chat_path.write_bytes(b"rewritten out of band\n")

    with pytest.raises(AgentsSyncFormatError, match="file digest mismatch"):
        load_validated_publication(repo)

    payload, resigned = repair_owner_hood_digests(target, repo, owner)

    assert payload
    assert any(entry.endswith("chat.md") for entry in resigned)
    assert all(entry.startswith("foo:") for entry in resigned)

    apply_payload_atomic(repo, payload)

    load_validated_publication(repo)


def test_repair_is_idempotent_on_healthy_sidecar(tmp_path: Path) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, repo = _publish(tmp_path, "case2", owner, "foo")

    payload, resigned = repair_owner_hood_digests(target, repo, owner)

    assert payload == {}
    assert resigned == ()


def test_repair_after_applying_a_fix_is_a_noop(tmp_path: Path) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, repo = _publish(tmp_path, "case3", owner, "foo")
    _chat_path(repo, owner, "foo").write_bytes(b"rewritten out of band\n")

    first_payload, first_resigned = repair_owner_hood_digests(target, repo, owner)
    apply_payload_atomic(repo, first_payload)
    assert first_resigned

    second_payload, second_resigned = repair_owner_hood_digests(target, repo, owner)

    assert second_payload == {}
    assert second_resigned == ()


def test_repair_never_touches_a_foreign_owners_snapshot(tmp_path: Path) -> None:
    alice = AgentOwnerIdentity("alice", "athena")
    bob = AgentOwnerIdentity("bob", "zeus")
    target, repo = _publish(tmp_path, "case4", alice, "foo")
    publish_agent_hood(
        target,
        repo,
        "bar",
        identity=AgentIdentitySnapshot(bob),
        inventory=ProjectHoodInventory(bob, "proj", (_run(bob, "bar", "02"),)),
    )

    _chat_path(repo, alice, "foo").write_bytes(b"alice rewritten out of band\n")
    _chat_path(repo, bob, "bar").write_bytes(b"bob rewritten out of band\n")
    bob_manifest_before = _manifest_path(repo, bob).read_bytes()
    bob_snapshot_path = (
        repo / "users" / "bob" / "machines" / "zeus" / "hoods" / "bar" / "snapshot.json"
    )
    bob_snapshot_before = bob_snapshot_path.read_bytes()

    payload, resigned = repair_owner_hood_digests(target, repo, alice)

    assert resigned and all(entry.startswith("foo:") for entry in resigned)
    assert str(_manifest_path(repo, bob).relative_to(repo)) not in payload
    assert str(bob_snapshot_path.relative_to(repo)) not in payload

    apply_payload_atomic(repo, payload)

    assert _manifest_path(repo, bob).read_bytes() == bob_manifest_before
    assert bob_snapshot_path.read_bytes() == bob_snapshot_before
    with pytest.raises(AgentsSyncFormatError, match="file digest mismatch"):
        load_validated_publication(repo)


def test_repair_manifest_restores_entries_for_intact_on_disk_hoods(
    tmp_path: Path,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, repo = _publish(tmp_path, "manifest1", owner, "foo")
    _manifest_path(repo, owner).unlink()

    payload, report = _repair_owner_manifest(target, repo, owner)

    assert payload
    assert any("foo" in entry and "recovered" in entry for entry in report)

    apply_payload_atomic(repo, payload)

    load_validated_publication(repo)


def test_repair_manifest_skips_and_reports_a_hood_with_a_pruned_run_file(
    tmp_path: Path,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, repo = _publish(tmp_path, "manifest2", owner, "foo")
    _manifest_path(repo, owner).unlink()
    _chat_path(repo, owner, "foo").unlink()

    payload, report = _repair_owner_manifest(target, repo, owner)

    assert payload == {}
    assert any("foo" in entry and "skipped" in entry for entry in report)


def test_repair_manifest_is_a_noop_when_already_complete(tmp_path: Path) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, repo = _publish(tmp_path, "manifest3", owner, "foo")

    payload, report = _repair_owner_manifest(target, repo, owner)

    assert payload == {}
    assert report == ()


def test_repair_manifest_normalizes_verified_apollo_style_stale_list(
    tmp_path: Path,
) -> None:
    owner = AgentOwnerIdentity("bbugyi200", "apollo")
    target = _target(tmp_path, "manifest-stale-list")
    repo = target.sidecar_path
    repo.mkdir()
    inventory = ProjectHoodInventory(owner, "proj", (_run(owner, "03", "01"),))
    publish_agent_hood(
        target,
        repo,
        "03",
        identity=AgentIdentitySnapshot(owner),
        inventory=inventory,
    )
    manifest_path = _manifest_path(repo, owner)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["hoods"]["03"]["files"] = _stale_files(
        owner, "03", _canonical_files(repo, owner, "03")
    )
    manifest["hoods"]["03"]["run_count"] = 9
    manifest["hoods"]["03"]["agent_session_count"] = 4
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    payload, report = _repair_owner_manifest(target, repo, owner)

    key = manifest_path.relative_to(repo).as_posix()
    repaired = json.loads(payload[key])
    assert report == ("03: repaired stale explicit file list",)
    assert "files" not in repaired["hoods"]["03"]
    assert repaired["hoods"]["03"]["run_count"] == 1
    assert repaired["hoods"]["03"]["agent_session_count"] == 0
    assert repaired["hoods"]["03"]["digest"] == manifest["hoods"]["03"]["digest"]

    apply_payload_atomic(repo, payload)
    load_validated_publication(repo)
    second_payload, second_report = _repair_owner_manifest(target, repo, owner)
    assert second_payload == {}
    assert second_report == ()


def test_repair_manifest_preserves_current_legacy_and_slim_entries(
    tmp_path: Path,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target = _target(tmp_path, "manifest-compatible-lists")
    repo = target.sidecar_path
    repo.mkdir()
    inventory = ProjectHoodInventory(
        owner,
        "proj",
        (
            _run(owner, "current", "01"),
            _run(owner, "legacy--member", "02", agent_session="legacy"),
            _run(owner, "slim", "03"),
        ),
    )
    for hood in ("current", "legacy", "slim"):
        publish_agent_hood(
            target,
            repo,
            hood,
            identity=AgentIdentitySnapshot(owner),
            inventory=inventory,
        )
    _set_explicit_files(
        repo, owner, "current", list(_canonical_files(repo, owner, "current"))
    )
    legacy_files = [
        path
        for path in _canonical_files(repo, owner, "legacy")
        if not path.startswith("sessions/")
    ]
    _set_explicit_files(repo, owner, "legacy", list(legacy_files))
    manifest_before = _manifest_path(repo, owner).read_bytes()

    payload, report = _repair_owner_manifest(target, repo, owner)

    assert payload == {}
    assert report == ()
    assert _manifest_path(repo, owner).read_bytes() == manifest_before


def test_repair_manifest_skips_corrupt_candidate_beside_a_valid_one(
    tmp_path: Path,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target = _target(tmp_path, "manifest-mixed-candidates")
    repo = target.sidecar_path
    repo.mkdir()
    for hood, suffix in (("foo", "01"), ("bar", "02")):
        hood_inventory = ProjectHoodInventory(
            owner, "proj", (_run(owner, hood, suffix),)
        )
        publish_agent_hood(
            target,
            repo,
            hood,
            identity=AgentIdentitySnapshot(owner),
            inventory=hood_inventory,
        )
    for hood in ("foo", "bar"):
        _set_explicit_files(
            repo,
            owner,
            hood,
            _stale_files(owner, hood, _canonical_files(repo, owner, hood)),
        )
    _chat_path(repo, owner, "bar").write_bytes(b"corrupt referenced payload\n")
    manifest_before = json.loads(
        _manifest_path(repo, owner).read_text(encoding="utf-8")
    )

    payload, report = _repair_owner_manifest(target, repo, owner)

    assert any("foo: repaired stale explicit file list" == item for item in report)
    assert any("bar: skipped explicit-list repair" in item for item in report)
    repaired = json.loads(
        payload[_manifest_path(repo, owner).relative_to(repo).as_posix()]
    )
    assert "files" not in repaired["hoods"]["foo"]
    assert repaired["hoods"]["bar"] == manifest_before["hoods"]["bar"]


def test_repair_manifest_reports_snapshot_digest_and_identity_mismatches(
    tmp_path: Path,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, repo = _publish(tmp_path, "manifest-invalid-snapshots", owner, "foo")
    _set_explicit_files(
        repo,
        owner,
        "foo",
        _stale_files(owner, "foo", _canonical_files(repo, owner, "foo")),
    )
    manifest_path = _manifest_path(repo, owner)
    manifest_before = manifest_path.read_bytes()
    snapshot_path = _snapshot_path(repo, owner, "foo")
    pristine_snapshot = snapshot_path.read_bytes()
    snapshot_path.write_bytes(pristine_snapshot + b" ")

    payload, report = _repair_owner_manifest(target, repo, owner)

    assert payload == {}
    assert any("snapshot digest mismatch" in item for item in report)
    assert manifest_path.read_bytes() == manifest_before

    snapshot = json.loads(pristine_snapshot)
    snapshot["owner"]["machine_name"] = "zeus"
    snapshot["hood"]["global_name"] = "alice.zeus.foo"
    snapshot["runs"][0]["global_name"] = "alice.zeus.foo"
    tampered_snapshot = v2_json_bytes(snapshot)
    snapshot_path.write_bytes(tampered_snapshot)
    manifest = json.loads(manifest_before)
    manifest["hoods"]["foo"]["digest"] = content_digest(tampered_snapshot)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    identity_mismatch_manifest = manifest_path.read_bytes()

    payload, report = _repair_owner_manifest(target, repo, owner)

    assert payload == {}
    assert any("snapshot identity mismatch" in item for item in report)
    assert manifest_path.read_bytes() == identity_mismatch_manifest


def test_repair_manifest_skips_unsafe_referenced_path_before_reading_it(
    tmp_path: Path,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, repo = _publish(tmp_path, "manifest-unsafe-path", owner, "foo")
    _set_explicit_files(
        repo,
        owner,
        "foo",
        _stale_files(owner, "foo", _canonical_files(repo, owner, "foo")),
    )
    path = _snapshot_path(repo, owner, "foo")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    run = snapshot["runs"][0]
    reference = next(iter(run["files"].values()))
    reference["path"] = "../outside"
    snapshot_bytes = v2_json_bytes(snapshot)
    path.write_bytes(snapshot_bytes)
    manifest_path = _manifest_path(repo, owner)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["hoods"]["foo"]["digest"] = content_digest(snapshot_bytes)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    payload, report = _repair_owner_manifest(target, repo, owner)

    assert payload == {}
    assert any(
        "skipped explicit-list repair" in item and "path" in item for item in report
    )


def test_repair_digest_writer_omits_explicit_file_lists(
    tmp_path: Path,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, repo = _publish(tmp_path, "flagdigest", owner, "foo")
    manifest_key = _manifest_path(repo, owner).relative_to(repo).as_posix()

    _chat_path(repo, owner, "foo").write_bytes(b"rewritten out of band\n")
    payload, resigned = repair_owner_hood_digests(target, repo, owner)
    assert resigned
    manifest = json.loads(payload[manifest_key])
    assert "files" not in manifest["hoods"]["foo"]


def test_repair_manifest_writer_omits_explicit_file_lists(
    tmp_path: Path,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, repo = _publish(tmp_path, "flagmanifest", owner, "foo")
    _manifest_path(repo, owner).unlink()
    manifest_key = _manifest_path(repo, owner).relative_to(repo).as_posix()

    payload, report = _repair_owner_manifest(target, repo, owner)
    assert any("foo" in entry and "recovered" in entry for entry in report)
    manifest = json.loads(payload[manifest_key])
    assert "files" not in manifest["hoods"]["foo"]


def test_repair_manifest_never_reads_a_foreign_owners_path_family(
    tmp_path: Path,
) -> None:
    alice = AgentOwnerIdentity("alice", "athena")
    bob = AgentOwnerIdentity("bob", "zeus")
    target, repo = _publish(tmp_path, "manifest4", alice, "foo")
    publish_agent_hood(
        target,
        repo,
        "bar",
        identity=AgentIdentitySnapshot(bob),
        inventory=ProjectHoodInventory(bob, "proj", (_run(bob, "bar", "02"),)),
    )
    _manifest_path(repo, alice).unlink()
    bob_manifest_before = _manifest_path(repo, bob).read_bytes()

    payload, report = _repair_owner_manifest(target, repo, alice)

    assert any("foo" in entry and "recovered" in entry for entry in report)
    assert all("bar" not in entry for entry in report)
    assert str(_manifest_path(repo, bob).relative_to(repo)) not in payload

    apply_payload_atomic(repo, payload)

    assert _manifest_path(repo, bob).read_bytes() == bob_manifest_before
