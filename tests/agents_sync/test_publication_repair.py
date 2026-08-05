from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.publication_repair import repair_owner_hood_digests
from sase.agents_sync.publication_validation import load_validated_publication
from sase.agents_sync.v2_io import apply_payload_atomic
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity


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


def _run(owner: AgentOwnerIdentity, name: str, suffix: str) -> InventoryRun:
    return InventoryRun(
        f"run-{suffix}",
        name,
        f"{owner.username}.{owner.machine_name}.{name}",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        (("model", "gpt"),),
        (),
        f"prompt for {name}\n".encode(),
        f"chat for {name}\n".encode(),
        None,
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
