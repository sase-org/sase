from __future__ import annotations

import pytest

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.v2_io import (
    MAX_RUNS,
    _hood_snapshot_from_json,
    content_digest,
    v2_json_bytes,
)
from sase.agents_sync.v2_models import (
    V2ContainerRecord,
    V2HoodSnapshot,
    V2ProjectIdentity,
    V2RunRecord,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity


OWNER = AgentOwnerIdentity("alice", "athena")
PROJECT = V2ProjectIdentity("proj", "Project")


def _snapshot() -> V2HoodSnapshot:
    return V2HoodSnapshot(
        OWNER,
        PROJECT,
        "foo",
        "alice.athena.foo",
        ("alice.athena.foo",),
        (
            V2RunRecord(
                "run-1",
                "foo",
                "alice.athena.foo",
                "active",
            ),
        ),
    )


def test_canonical_json_digest_and_strict_snapshot_round_trip() -> None:
    first = v2_json_bytes({"z": 1, "a": 2})
    second = v2_json_bytes({"a": 2, "z": 1})

    assert first == second == b'{"a":2,"z":1}\n'
    assert content_digest(first) == content_digest(second)
    assert _hood_snapshot_from_json(_snapshot().to_json_dict()) == _snapshot()

    malformed = _snapshot().to_json_dict()
    malformed["generated_at"] = "volatile"
    with pytest.raises(AgentsSyncFormatError, match="invalid shape"):
        _hood_snapshot_from_json(malformed)


def test_container_commits_round_trip_and_legacy_snapshots_remain_readable() -> None:
    commits = (
        CommitRecord("a" * 40, "first", 1),
        CommitRecord("b" * 40, "second", 2),
    )
    run = V2RunRecord(
        "run-1",
        "foo--code",
        "alice.athena.foo--code",
        "completed",
    )
    snapshot = V2HoodSnapshot(
        OWNER,
        PROJECT,
        "foo",
        "alice.athena.foo",
        runs=(run,),
        containers=(
            V2ContainerRecord(
                "family",
                "alice.athena.foo",
                ("run-1",),
                commits,
            ),
        ),
    )

    encoded = snapshot.to_json_dict()
    assert encoded["schema_version"] == 2
    assert encoded["containers"][0]["commits"] == [  # type: ignore[index]
        commit.to_json_dict() for commit in commits
    ]
    assert "commits" not in snapshot.relationship_batch()["containers"][0]  # type: ignore[index]
    assert _hood_snapshot_from_json(encoded) == snapshot

    legacy = snapshot.to_json_dict()
    legacy["containers"][0].pop("commits")  # type: ignore[index, union-attr]
    assert _hood_snapshot_from_json(legacy).containers == (
        V2ContainerRecord("family", "alice.athena.foo", ("run-1",)),
    )


def test_empty_container_commits_have_stable_canonical_digest() -> None:
    run = V2RunRecord(
        "run-1",
        "foo--code",
        "alice.athena.foo--code",
        "completed",
    )
    snapshot = V2HoodSnapshot(
        OWNER,
        PROJECT,
        "foo",
        "alice.athena.foo",
        runs=(run,),
        containers=(V2ContainerRecord("family", "alice.athena.foo", ("run-1",)),),
    )

    first = v2_json_bytes(snapshot.to_json_dict())
    decoded = _hood_snapshot_from_json(snapshot.to_json_dict())
    second = v2_json_bytes(decoded.to_json_dict())

    assert b'"commits":[]' in first
    assert first == second
    assert content_digest(first) == content_digest(second)


def test_container_commit_validation_is_strict() -> None:
    snapshot = V2HoodSnapshot(
        OWNER,
        PROJECT,
        "foo",
        "alice.athena.foo",
        containers=(V2ContainerRecord("family", "alice.athena.foo", ()),),
    ).to_json_dict()
    container = snapshot["containers"][0]  # type: ignore[index]
    container["commits"] = [  # type: ignore[index]
        CommitRecord("b" * 40, "second", 2).to_json_dict(),
        CommitRecord("a" * 40, "first", 1).to_json_dict(),
    ]
    with pytest.raises(AgentsSyncFormatError, match="stably sorted"):
        _hood_snapshot_from_json(snapshot)

    container["commits"] = [  # type: ignore[index]
        CommitRecord("a" * 40, "first", 1).to_json_dict(),
        CommitRecord("a" * 40, "duplicate", 2).to_json_dict(),
    ]
    with pytest.raises(AgentsSyncFormatError, match="unique SHAs"):
        _hood_snapshot_from_json(snapshot)

    container["kind"] = "clan"  # type: ignore[index]
    container["global_name"] = "alice.athena.workers"  # type: ignore[index]
    container["commits"] = [  # type: ignore[index]
        CommitRecord("a" * 40, "first", 1).to_json_dict()
    ]
    with pytest.raises(AgentsSyncFormatError, match="clan commits must be empty"):
        _hood_snapshot_from_json(snapshot)


def test_snapshot_count_limit_is_enforced_before_relationship_validation() -> None:
    malformed = _snapshot().to_json_dict()
    malformed["runs"] = [malformed["runs"][0]] * (MAX_RUNS + 1)  # type: ignore[index]
    with pytest.raises(AgentsSyncFormatError, match="count limit"):
        _hood_snapshot_from_json(malformed)
