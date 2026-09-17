from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.v2_io import (
    MAX_MANIFEST_HOODS,
    MAX_MANIFEST_JSON_BYTES,
    MAX_RUNS,
    _hood_snapshot_from_json,
    _owner_manifest_from_json,
    apply_payload_atomic,
    apply_payload_batched_atomic,
    check_manifest_write_size,
    content_digest,
    v2_json_bytes,
    validate_relative_path,
)
from sase.agents_sync.v2_models import (
    V2ContainerRecord,
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2RunRecord,
)
from sase.agents_sync.v2_run_io import (
    run_commits_from_json,
    run_metadata_from_json,
    run_state_from_json,
)
from sase.core import agent_output_variables
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.output_variable_values import (
    MAX_OUTPUT_VARIABLE_DEPTH,
    MAX_OUTPUT_VARIABLE_ENCODED_BYTES,
    MAX_OUTPUT_VARIABLE_NODES,
)


OWNER = AgentOwnerIdentity("alice", "athena")
PROJECT = V2ProjectIdentity("proj", "Project")


def _batch_plan(
    batch_specs: tuple[tuple[tuple[str, ...], int], ...],
    *,
    budget_bytes: int,
    total_size_bytes: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        schema_version=1,
        budget_bytes=budget_bytes,
        total_size_bytes=total_size_bytes,
        batches=tuple(
            SimpleNamespace(paths=paths, size_bytes=size) for paths, size in batch_specs
        ),
    )


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


def test_output_variable_limits_are_shared_with_storage() -> None:
    from sase.agents_sync import v2_io, v2_validation

    assert (
        v2_validation.MAX_OUTPUT_VARIABLES
        is agent_output_variables.MAX_OUTPUT_VARIABLES
    )
    assert (
        v2_validation.MAX_OUTPUT_VARIABLE_VALUE_BYTES
        is agent_output_variables.MAX_OUTPUT_VARIABLE_VALUE_BYTES
    )
    assert v2_validation.MAX_OUTPUT_VARIABLE_DEPTH is MAX_OUTPUT_VARIABLE_DEPTH
    assert (
        v2_validation.MAX_OUTPUT_VARIABLE_ENCODED_BYTES
        is MAX_OUTPUT_VARIABLE_ENCODED_BYTES
    )
    assert v2_validation.MAX_OUTPUT_VARIABLE_NODES is MAX_OUTPUT_VARIABLE_NODES
    assert v2_io.MAX_OUTPUT_VARIABLES is agent_output_variables.MAX_OUTPUT_VARIABLES
    assert (
        v2_io.MAX_OUTPUT_VARIABLE_VALUE_BYTES
        is agent_output_variables.MAX_OUTPUT_VARIABLE_VALUE_BYTES
    )
    assert v2_io.MAX_OUTPUT_VARIABLE_DEPTH is MAX_OUTPUT_VARIABLE_DEPTH
    assert v2_io.MAX_OUTPUT_VARIABLE_ENCODED_BYTES is MAX_OUTPUT_VARIABLE_ENCODED_BYTES
    assert v2_io.MAX_OUTPUT_VARIABLE_NODES is MAX_OUTPUT_VARIABLE_NODES


def test_owner_manifest_and_path_validation_are_strict() -> None:
    manifest = V2OwnerManifest(OWNER, PROJECT)
    assert _owner_manifest_from_json(manifest.to_json_dict()) == manifest

    malformed = manifest.to_json_dict()
    malformed["owner"] = {"username": "Alice", "machine_name": "athena"}
    with pytest.raises(AgentsSyncFormatError, match="invalid owner"):
        _owner_manifest_from_json(malformed)

    for unsafe in ("../escape", "/absolute", "users//manifest.json", ".secret"):
        with pytest.raises(AgentsSyncFormatError):
            validate_relative_path(unsafe)
    assert validate_relative_path("agents/.gitkeep") == "agents/.gitkeep"


def test_owner_manifest_decode_is_forward_compatible_and_self_healing() -> None:
    manifest = V2OwnerManifest(
        OWNER,
        PROJECT,
        (
            (
                "foo",
                V2OwnerHoodEntry(
                    "a" * 64,
                    (
                        "agents/alice.athena.foo/README.md",
                        "users/alice/machines/athena/hoods/foo/snapshot.json",
                    ),
                    1,
                    0,
                ),
            ),
        ),
    )
    encoded = manifest.to_json_dict()
    encoded["compatibility_aliases"] = []
    encoded["hoods"]["foo"]["future_field"] = "ignored"  # type: ignore[index]

    decoded = _owner_manifest_from_json(encoded)

    assert decoded == manifest
    healed = decoded.to_json_dict()
    assert "compatibility_aliases" not in healed
    assert "future_field" not in healed["hoods"]["foo"]  # type: ignore[index]

    missing = manifest.to_json_dict()
    missing.pop("project")
    with pytest.raises(AgentsSyncFormatError, match="missing required keys: project"):
        _owner_manifest_from_json(missing)


def test_owner_manifest_hood_entries_decode_fat_and_slim_shapes() -> None:
    fat = V2OwnerManifest(
        OWNER,
        PROJECT,
        (
            (
                "foo",
                V2OwnerHoodEntry(
                    "a" * 64,
                    (
                        "agents/alice.athena.foo/README.md",
                        "users/alice/machines/athena/hoods/foo/snapshot.json",
                    ),
                    1,
                    0,
                ),
            ),
        ),
    )
    slim = V2OwnerManifest(
        OWNER,
        PROJECT,
        (("bar", V2OwnerHoodEntry("b" * 64, None, 2, 1)),),
    )

    fat_encoded = fat.to_json_dict()
    assert "files" in fat_encoded["hoods"]["foo"]  # type: ignore[index]
    assert _owner_manifest_from_json(fat_encoded) == fat

    slim_encoded = slim.to_json_dict()
    assert "files" not in slim_encoded["hoods"]["bar"]  # type: ignore[index]
    decoded_slim = _owner_manifest_from_json(slim_encoded)
    assert decoded_slim == slim
    assert decoded_slim.hoods[0][1].files is None

    # A slim entry round-trips byte-for-byte: re-encoding never resurrects
    # the omitted key.
    assert v2_json_bytes(decoded_slim.to_json_dict()) == v2_json_bytes(slim_encoded)

    missing_run_count = slim_encoded["hoods"]["bar"].copy()  # type: ignore[index]
    del missing_run_count["run_count"]
    broken = {**slim_encoded, "hoods": {"bar": missing_run_count}}
    with pytest.raises(AgentsSyncFormatError, match="missing required keys: run_count"):
        _owner_manifest_from_json(broken)


def test_owner_manifest_uses_dedicated_larger_read_caps() -> None:
    from sase.agents_sync import v2_io, v2_validation

    assert v2_validation.MAX_MANIFEST_JSON_BYTES is MAX_MANIFEST_JSON_BYTES
    assert v2_validation.MAX_MANIFEST_HOODS is MAX_MANIFEST_HOODS
    assert MAX_MANIFEST_JSON_BYTES > v2_io.MAX_JSON_BYTES
    assert MAX_MANIFEST_HOODS > v2_io.MAX_CONTAINERS

    many_hoods = V2OwnerManifest(
        OWNER,
        PROJECT,
        tuple(
            (f"hood{index:05d}", V2OwnerHoodEntry("a" * 64, None, 0, 0))
            for index in range(v2_io.MAX_CONTAINERS + 1)
        ),
    )
    encoded = many_hoods.to_json_dict()
    # Exceeds the old MAX_CONTAINERS cap but stays under MAX_MANIFEST_HOODS.
    assert _owner_manifest_from_json(encoded).hoods == many_hoods.hoods

    too_many = {
        **encoded,
        "hoods": {
            f"hood{index:05d}": {"digest": "a" * 64, "run_count": 0, "family_count": 0}
            for index in range(MAX_MANIFEST_HOODS + 1)
        },
    }
    with pytest.raises(AgentsSyncFormatError, match="too many hoods"):
        _owner_manifest_from_json(too_many)


def test_owner_manifest_write_guard_rejects_oversized_writes() -> None:
    check_manifest_write_size(0, b"{}")

    with pytest.raises(AgentsSyncFormatError, match="byte read cap"):
        check_manifest_write_size(0, b"x" * (MAX_MANIFEST_JSON_BYTES + 1))

    with pytest.raises(AgentsSyncFormatError, match="hood read cap"):
        check_manifest_write_size(MAX_MANIFEST_HOODS + 1, b"{}")


def test_old_reader_lenient_skips_a_slim_manifest_entry() -> None:
    """Freeze the pre-slim per-hood decode contract.

    Before this change, every hood entry's shape was checked with
    ``compatible_object(..., {"digest", "files", "run_count",
    "family_count"})``, which requires every one of those keys. A slim entry
    (files omitted) fails that check, so an old sase binary's
    ``read_all_owner_manifests_lenient`` catches the resulting
    ``AgentsSyncFormatError`` and skips just that manifest instead of
    hard-failing the whole read. This is the compatibility promise that lets
    a slim manifest roll out before every owner machine upgrades: keep it
    locked in by re-running that frozen legacy shape check directly.
    """
    from sase.agents_sync.v2_validation import compatible_object

    def _legacy_hood_entry_shape_check(raw_entry: object, hood: str) -> None:
        compatible_object(
            raw_entry,
            f"hood {hood!r}",
            {"digest", "files", "run_count", "family_count"},
        )

    slim_entry = {"digest": "a" * 64, "run_count": 1, "family_count": 0}
    with pytest.raises(AgentsSyncFormatError, match="missing required keys: files"):
        _legacy_hood_entry_shape_check(slim_entry, "foo")

    fat_entry = {**slim_entry, "files": []}
    _legacy_hood_entry_shape_check(fat_entry, "foo")  # does not raise


def test_snapshot_count_limit_is_enforced_before_relationship_validation() -> None:
    malformed = _snapshot().to_json_dict()
    malformed["runs"] = [malformed["runs"][0]] * (MAX_RUNS + 1)  # type: ignore[index]
    with pytest.raises(AgentsSyncFormatError, match="count limit"):
        _hood_snapshot_from_json(malformed)


def test_per_run_payloads_reject_unknown_or_host_local_fields() -> None:
    meta = {
        "schema_version": 2,
        "owner": {"username": "alice", "machine_name": "athena"},
        "project": {"key": "proj", "name": "Project"},
        "source_run_id": "run-1",
        "local_name": "foo",
        "global_name": "alice.athena.foo",
        "metadata": {"model": "gpt"},
    }
    assert run_metadata_from_json(meta).metadata == (("model", "gpt"),)
    meta["metadata"] = {"workspace_dir": "/private"}
    with pytest.raises(AgentsSyncFormatError, match="unsupported fields"):
        run_metadata_from_json(meta)

    state = {
        "schema_version": 2,
        "source_run_id": "run-1",
        "state": "waiting",
        "started_at": None,
        "finished_at": None,
        "dismissed_at": None,
    }
    assert run_state_from_json(state).state == "waiting"
    state["pid"] = 99
    with pytest.raises(AgentsSyncFormatError, match="invalid shape"):
        run_state_from_json(state)

    commits = {
        "schema_version": 2,
        "source_run_id": "run-1",
        "commits": [{"sha": "a" * 40, "subject": "subject", "committed_at": 1}],
    }
    assert run_commits_from_json(commits).commits[0].sha == "a" * 40


def test_output_variables_are_accepted_by_snapshot_and_per_run_decoders() -> None:
    variables = {
        "z_path": "reports/z.md",
        "a_config": {
            "enabled": True,
            "limits": [1, 2.5, None],
        },
        "empty": [],
    }
    snapshot = _snapshot().to_json_dict()
    snapshot["runs"][0]["metadata"] = {"output_variables": variables}  # type: ignore[index]
    decoded_snapshot = _hood_snapshot_from_json(snapshot)

    meta = _run_metadata({"output_variables": variables})
    decoded_meta = run_metadata_from_json(meta)

    assert dict(decoded_snapshot.runs[0].metadata)["output_variables"] == variables
    assert dict(decoded_meta.metadata)["output_variables"] == variables


@pytest.mark.parametrize(
    ("variables", "message"),
    (
        (["not", "an", "object"], "must be a JSON object"),
        ({"bad-key": "value"}, "invalid key.*bad-key"),
        ({"valid_key": object()}, "valid_key.*must be a JSON value"),
        (
            {"valid_key": {"nested": "x" * 8_193}},
            r"valid_key.*valid_key\.nested.*8192",
        ),
        (
            {"valid_key": {"": "value"}},
            "valid_key.*map key at valid_key must not be empty",
        ),
        (
            {"valid_key": 2**63},
            "valid_key.*valid_key.*signed 64-bit range",
        ),
        (
            {"valid_key": float("nan")},
            "valid_key.*valid_key.*must be finite",
        ),
        (
            {f"key_{index}": "value" for index in range(257)},
            "256 entry limit",
        ),
    ),
)
def test_output_variables_are_strictly_validated_in_both_decoders(
    variables: object,
    message: str,
) -> None:
    snapshot = _snapshot().to_json_dict()
    snapshot["runs"][0]["metadata"] = {"output_variables": variables}  # type: ignore[index]
    with pytest.raises(AgentsSyncFormatError, match=message):
        _hood_snapshot_from_json(snapshot)

    with pytest.raises(AgentsSyncFormatError, match=message):
        run_metadata_from_json(_run_metadata({"output_variables": variables}))


@pytest.mark.parametrize(
    ("value", "message"),
    (
        (
            [[[[[[[[[0]]]]]]]]],
            "maximum depth 8",
        ),
        (
            [0] * MAX_OUTPUT_VARIABLE_NODES,
            "1024-node limit",
        ),
        (
            ["x" * 8_192] * 8,
            "encoded UTF-8 bytes.*limit is 65536",
        ),
    ),
)
def test_output_variable_structural_caps_are_strictly_validated(
    value: object,
    message: str,
) -> None:
    with pytest.raises(AgentsSyncFormatError, match=message):
        run_metadata_from_json(
            _run_metadata({"output_variables": {"valid_key": value}})
        )


def test_payload_apply_rolls_back_every_prior_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import v2_io

    first = tmp_path / "a.txt"
    first.write_text("old", encoding="utf-8")
    real_write = v2_io.atomic_write_bytes
    calls = 0

    def fail_once(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected")
        real_write(path, payload)

    monkeypatch.setattr(v2_io, "atomic_write_bytes", fail_once)
    with pytest.raises(OSError, match="injected"):
        apply_payload_atomic(
            tmp_path,
            {"a.txt": b"new", "nested/b.txt": b"created"},
        )

    assert first.read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "nested" / "b.txt").exists()


def test_batched_payload_ignores_unchanged_bytes_when_planning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import v2_io

    (tmp_path / "unchanged-a.txt").write_bytes(b"a" * 8)
    (tmp_path / "unchanged-b.txt").write_bytes(b"b" * 8)
    seen: list[tuple[tuple[str, int], ...]] = []

    def fake_plan(records, *, budget_bytes: int):  # type: ignore[no-untyped-def]
        materialized = tuple((record.path, record.size_bytes) for record in records)
        seen.append(materialized)
        return _batch_plan(
            tuple(((path,), size) for path, size in materialized),
            budget_bytes=budget_bytes,
            total_size_bytes=sum(size for _path, size in materialized),
        )

    monkeypatch.setattr(v2_io, "plan_agent_publication_batches", fake_plan)

    assert apply_payload_batched_atomic(
        tmp_path,
        {
            "unchanged-a.txt": b"a" * 8,
            "unchanged-b.txt": b"b" * 8,
            "changed.txt": b"c",
        },
        batch_budget_bytes=1,
    )

    assert seen == [(("changed.txt", 1),)]
    assert (tmp_path / "changed.txt").read_bytes() == b"c"


def test_batched_payload_applies_all_changed_payload_over_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import v2_io

    planned: list[tuple[int, tuple[tuple[str, int], ...]]] = []

    def fake_plan(records, *, budget_bytes: int):  # type: ignore[no-untyped-def]
        materialized = tuple((record.path, record.size_bytes) for record in records)
        planned.append((budget_bytes, materialized))
        return _batch_plan(
            (
                (("a.txt", "b.txt"), 4),
                (("c.txt",), 2),
            ),
            budget_bytes=budget_bytes,
            total_size_bytes=sum(size for _path, size in materialized),
        )

    monkeypatch.setattr(v2_io, "plan_agent_publication_batches", fake_plan)

    assert apply_payload_batched_atomic(
        tmp_path,
        {"a.txt": b"aa", "b.txt": b"bb", "c.txt": b"cc"},
        batch_budget_bytes=4,
    )

    assert planned == [(4, (("a.txt", 2), ("b.txt", 2), ("c.txt", 2)))]
    assert (tmp_path / "a.txt").read_bytes() == b"aa"
    assert (tmp_path / "b.txt").read_bytes() == b"bb"
    assert (tmp_path / "c.txt").read_bytes() == b"cc"


def test_batched_payload_rolls_back_across_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import v2_io

    first = tmp_path / "a.txt"
    first.write_text("old", encoding="utf-8")

    def fake_plan(records, *, budget_bytes: int):  # type: ignore[no-untyped-def]
        materialized = tuple(record.path for record in records)
        assert materialized == ("a.txt", "nested/b.txt")
        return _batch_plan(
            (
                (("a.txt",), 3),
                (("nested/b.txt",), 3),
            ),
            budget_bytes=budget_bytes,
            total_size_bytes=6,
        )

    real_write = v2_io.atomic_write_bytes
    calls = 0

    def fail_second_batch(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected")
        real_write(path, payload)

    monkeypatch.setattr(v2_io, "plan_agent_publication_batches", fake_plan)
    monkeypatch.setattr(v2_io, "atomic_write_bytes", fail_second_batch)

    with pytest.raises(OSError, match="injected"):
        apply_payload_batched_atomic(
            tmp_path,
            {"a.txt": b"new", "nested/b.txt": b"new"},
            batch_budget_bytes=3,
        )

    assert first.read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "nested" / "b.txt").exists()
    assert not tuple(tmp_path.glob(".sase-v2-stage-*"))
    assert not tuple(tmp_path.glob(".sase-v2-backup-*"))


def test_batched_payload_stage_failure_leaves_destinations_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import v2_io

    first = tmp_path / "a.txt"
    first.write_text("old", encoding="utf-8")

    def fake_plan(records, *, budget_bytes: int):  # type: ignore[no-untyped-def]
        materialized = tuple(record.path for record in records)
        return _batch_plan(
            tuple(((path,), 3) for path in materialized),
            budget_bytes=budget_bytes,
            total_size_bytes=3 * len(materialized),
        )

    def fail_stage(_stage, _changed):  # type: ignore[no-untyped-def]
        raise OSError("staging failed")

    monkeypatch.setattr(v2_io, "plan_agent_publication_batches", fake_plan)
    monkeypatch.setattr(v2_io, "_stage_changed_payload", fail_stage)

    with pytest.raises(OSError, match="staging failed"):
        apply_payload_batched_atomic(
            tmp_path,
            {"a.txt": b"new", "nested/b.txt": b"new"},
            batch_budget_bytes=3,
        )

    assert first.read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "nested" / "b.txt").exists()
    assert not tuple(tmp_path.glob(".sase-v2-stage-*"))
    assert not tuple(tmp_path.glob(".sase-v2-backup-*"))


def _run_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "owner": {"username": "alice", "machine_name": "athena"},
        "project": {"key": "proj", "name": "Project"},
        "source_run_id": "run-1",
        "local_name": "foo",
        "global_name": "alice.athena.foo",
        "metadata": metadata,
    }
