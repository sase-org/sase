"""Targeted payload-scope publication: subset, indexes, and isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.publication import publish_agent_hood, reconcile_agent_hoods
from sase.agents_sync.publication_planning import (
    plan_hoods,
    plan_targeted_hoods,
    shared_targeted_planning,
)
from sase.agents_sync.publication_validation import read_hood_snapshot
from sase.agents_sync.v2_io import v2_json_bytes
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from tests.agents_sync.publication_fixtures import _identity, _inventory, _target


def _disk_bytes(repo: Path) -> dict[str, bytes]:
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file()
    }


def _bob_inventory() -> tuple[AgentIdentitySnapshot, ProjectHoodInventory]:
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
        (CommitRecord("b" * 40, "other", 2),),
        b"other\n",
        b"chat\n",
        None,
        None,
        (),
        "20260723130000",
    )
    return (
        AgentIdentitySnapshot(bob_owner),
        ProjectHoodInventory(bob_owner, "proj", (bob_run,)),
    )


def test_targeted_pages_match_full_subset_and_scale(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    owner = AgentOwnerIdentity("alice", "athena")

    full_payload, _ = plan_hoods(target, repo, inventory, ("foo", "zap"), owner)
    targeted_payload, _ = plan_targeted_hoods(target, repo, inventory, ("foo",), owner)

    # Every selected hood/agent/session/legacy page matches the full output.
    foo_keys = [
        key
        for key in targeted_payload
        if "/hoods/foo/" in key
        or key.startswith("agents/alice.athena.foo")
        or key.startswith("sessions/alice.athena.foo")
        or key.startswith("families/alice.athena.foo")
    ]
    assert foo_keys
    for key in foo_keys:
        assert targeted_payload[key] == full_payload[key]
    # Unrelated hood pages are omitted from the targeted payload.
    assert not any(
        "/hoods/zap/" in key
        or key.startswith("agents/alice.athena.zap")
        or key.startswith("sessions/alice.athena.zap")
        for key in targeted_payload
    )
    # The payload scales with the selection, not every run page.
    assert len(targeted_payload) < len(full_payload)
    assert sum(map(len, targeted_payload.values())) < sum(
        map(len, full_payload.values())
    )
    # Selecting every hood converges with full reconciliation output.
    both_payload, _ = plan_targeted_hoods(
        target, repo, inventory, ("foo", "zap"), owner
    )
    assert len(both_payload) > len(targeted_payload)
    assert both_payload == full_payload


def test_targeted_publish_preserves_unselected_and_completes_indexes(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))

    publish_agent_hood(
        target, repo, "foo.bar.baz--code", identity=_identity(), inventory=inventory
    )
    before = _disk_bytes(repo)
    assert "users/alice/machines/athena/hoods/foo/snapshot.json" in before

    publish_agent_hood(
        target, repo, "zap.solo", identity=_identity(), inventory=inventory
    )
    after = _disk_bytes(repo)

    # Unselected hood files are byte-identical after publishing another hood.
    for key in (
        "users/alice/machines/athena/hoods/foo/snapshot.json",
        "users/alice/machines/athena/hoods/foo/README.md",
        "agents/alice.athena.foo.bar.baz--code/README.md",
        "sessions/alice.athena.foo.bar.baz.md",
    ):
        assert after[key] == before[key]
    # The manifest retains complete entries for every published hood.
    manifest_path = repo / "users/alice/machines/athena/manifest.json"
    manifest = read_hood_snapshot(
        repo / "users/alice/machines/athena/hoods/foo/snapshot.json"
    )
    assert manifest.local_hood == "foo"
    assert manifest_path.is_file()
    # Aggregate indexes stay complete: both hoods listed with totals.
    machine = (repo / "users/alice/machines/athena/README.md").read_text(
        encoding="utf-8"
    )
    assert "foo" in machine and "zap" in machine
    root = (repo / "README.md").read_text(encoding="utf-8")
    assert "Hoods:" in root


def test_targeted_empty_selection_is_noop(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))

    payload, counts = plan_targeted_hoods(
        target, repo, inventory, (), AgentOwnerIdentity("alice", "athena")
    )
    assert set(payload) == {
        "schema.json",
        "agents/.gitkeep",
        "families/.gitkeep",
        "sessions/.gitkeep",
    }
    assert counts.hoods_published == 0
    assert counts.hoods_refreshed == 0
    assert counts.hoods_unchanged == 0
    assert counts.runs_published == 0


def test_targeted_keeps_legacy_redirects_and_machine_states(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))

    publish_agent_hood(
        target, repo, "foo.bar.baz--code", identity=_identity(), inventory=inventory
    )
    publish_agent_hood(
        target, repo, "zap.solo", identity=_identity(), inventory=inventory
    )

    # Legacy family redirect stubs ship with selected session pages.
    assert (repo / "sessions" / "alice.athena.foo.bar.baz.md").is_file()
    assert (repo / "families" / "alice.athena.foo.bar.baz.md").is_file()
    # The machine index preserves the states column for every published hood.
    machine = (repo / "users/alice/machines/athena/README.md").read_text(
        encoding="utf-8"
    )
    assert "| Hood | Runs | Sessions | States |" in machine
    assert "foo" in machine and "zap" in machine


def test_targeted_leaves_foreign_owner_pages_untouched(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    alice_inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    reconcile_agent_hoods(target, repo, identity=_identity(), inventory=alice_inventory)
    bob_identity, bob_inventory = _bob_inventory()
    reconcile_agent_hoods(target, repo, identity=bob_identity, inventory=bob_inventory)
    bob_before = {
        key: value
        for key, value in _disk_bytes(repo).items()
        if "/bob/" in key or key.startswith("users/bob/")
    }
    assert bob_before

    # The targeted plan never includes another owner's pages, so applying it
    # cannot overwrite that machine's new pages from a stale payload.
    planned, _ = plan_targeted_hoods(
        target,
        repo,
        alice_inventory,
        ("zap",),
        AgentOwnerIdentity("alice", "athena"),
    )
    assert not any(key.startswith("users/bob/") or "/bob/" in key for key in planned)

    publish_agent_hood(
        target, repo, "zap.solo", identity=_identity(), inventory=alice_inventory
    )
    bob_after = {
        key: value
        for key, value in _disk_bytes(repo).items()
        if "/bob/" in key or key.startswith("users/bob/")
    }
    assert bob_after == bob_before
    root = (repo / "README.md").read_text(encoding="utf-8")
    assert "bob" in root


def test_targeted_rejects_malformed_unrelated_manifest(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    reconcile_agent_hoods(target, repo, identity=_identity(), inventory=inventory)

    # A foreign manifest entry with no snapshot behind it is malformed: the
    # targeted drain must fail rather than ignore it for a clean canary.
    bob_owner = AgentOwnerIdentity("bob", "zeus")
    ghost = V2OwnerManifest(
        bob_owner,
        V2ProjectIdentity("proj", "Project"),
        (("ghost", V2OwnerHoodEntry("a" * 64, None, 0, 0)),),
    )
    ghost_path = repo / "users/bob/machines/zeus/manifest.json"
    ghost_path.parent.mkdir(parents=True, exist_ok=True)
    ghost_path.write_bytes(v2_json_bytes(ghost.to_json_dict()))

    with pytest.raises(AgentsSyncFormatError):
        plan_targeted_hoods(
            target, repo, inventory, ("foo",), AgentOwnerIdentity("alice", "athena")
        )


def test_targeted_shares_validation_within_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    owner = AgentOwnerIdentity("alice", "athena")
    reconcile_agent_hoods(target, repo, identity=_identity(), inventory=inventory)

    import sase.agents_sync.publication_validation as validation

    real_read = validation.read_hood_snapshot
    calls: list[tuple[str, str, str]] = []

    def counting(path: Path):  # type: ignore[no-untyped-def]
        snapshot = real_read(path)
        calls.append(
            (snapshot.owner.username, snapshot.owner.machine_name, snapshot.local_hood)
        )
        return snapshot

    monkeypatch.setattr(validation, "read_hood_snapshot", counting)
    # previous_snapshot resolves through the same module-global read.
    import sase.agents_sync.publication_planning as planning

    monkeypatch.setattr(planning, "read_hood_snapshot", counting, raising=False)

    with shared_targeted_planning():
        shared_first, _ = plan_targeted_hoods(target, repo, inventory, ("foo",), owner)
        shared_calls_first = len(calls)
        shared_second, _ = plan_targeted_hoods(
            target, repo, inventory, ("work",), owner
        )
        shared_calls_total = len(calls)
    calls.clear()
    outside_first, _ = plan_targeted_hoods(target, repo, inventory, ("foo",), owner)
    outside_calls_first = len(calls)
    outside_second, _ = plan_targeted_hoods(target, repo, inventory, ("work",), owner)
    outside_calls_total = len(calls)

    # Sharing never changes the payload: cached validation matches fresh.
    assert shared_first == outside_first
    assert shared_second == outside_second
    # The second plan in one transaction reuses validated snapshots.
    assert shared_calls_total < outside_calls_total
    assert shared_calls_first == outside_calls_first
