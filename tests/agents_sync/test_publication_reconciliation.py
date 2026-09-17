from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.publication import publish_agent_hood, reconcile_agent_hoods
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from tests.agents_sync.publication_fixtures import _identity, _inventory, _target


def test_full_reconciliation_discovers_only_commit_eligible_hoods(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()

    counts = reconcile_agent_hoods(
        target,
        repo,
        identity=_identity(),
        inventory=_inventory(AgentOwnerIdentity("alice", "athena")),
    )

    machine = repo / "users" / "alice" / "machines" / "athena"
    assert counts.hoods_published == 2
    assert (machine / "hoods" / "foo" / "snapshot.json").is_file()
    assert (machine / "hoods" / "work" / "snapshot.json").is_file()
    assert not (machine / "hoods" / "zap").exists()


def test_two_owner_manifests_coexist_and_indexes_converge(tmp_path: Path) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    alice = _inventory(AgentOwnerIdentity("alice", "athena"))
    reconcile_agent_hoods(
        target,
        repo,
        identity=_identity(),
        inventory=alice,
    )
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
    reconcile_agent_hoods(
        target,
        repo,
        identity=AgentIdentitySnapshot(bob_owner),
        inventory=ProjectHoodInventory(bob_owner, "proj", (bob_run,)),
    )

    assert (
        repo / "users" / "alice" / "machines" / "athena" / "manifest.json"
    ).is_file()
    assert (repo / "users" / "bob" / "machines" / "zeus" / "manifest.json").is_file()
    root = (repo / "README.md").read_text(encoding="utf-8")
    assert "alice" in root and "bob" in root


def test_scoped_verification_ignores_drift_outside_the_hood_being_published(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    repo = target.sidecar_path
    repo.mkdir()
    inventory = _inventory(AgentOwnerIdentity("alice", "athena"))
    reconcile_agent_hoods(
        target,
        repo,
        identity=_identity(),
        inventory=inventory,
    )

    drifted_chat = repo / "agents" / "alice.athena.work.committer" / "chat.md"
    assert drifted_chat.is_file()
    drifted_chat.write_bytes(b"rewritten out of band\n")

    # Publishing an unrelated hood ("foo") no longer re-hashes every other
    # hood's run files, so drift in "work" does not block it.
    counts = publish_agent_hood(
        target,
        repo,
        "foo.bar.baz--code",
        identity=_identity(),
        inventory=inventory,
    )
    assert counts.hoods_unchanged == 1

    # A carried-forward ("temporarily absent") run inside the hood actually
    # being published is still verified: drift in its own referenced file
    # blocks that hood's own publish.
    without_boom = ProjectHoodInventory(
        inventory.owner,
        "proj",
        tuple(run for run in inventory.runs if run.local_name != "foo.boom"),
    )
    boom_chat = repo / "agents" / "alice.athena.foo.boom" / "chat.md"
    assert boom_chat.is_file()
    boom_chat.write_bytes(b"rewritten out of band\n")

    with pytest.raises(AgentsSyncFormatError, match="file digest mismatch"):
        publish_agent_hood(
            target,
            repo,
            "foo.bar.baz--code",
            identity=_identity(),
            inventory=without_boom,
        )
