from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_io import (
    MAX_RUNS,
    _hood_snapshot_from_json,
    _owner_manifest_from_json,
    apply_payload_atomic,
    content_digest,
    v2_json_bytes,
    validate_relative_path,
)
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2RunRecord,
)
from sase.agents_sync.v2_run_io import (
    run_commits_from_json,
    run_metadata_from_json,
    run_state_from_json,
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
    variables = {"z_path": "reports/z.md", "a_status": "ready"}
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
        ({"valid_key": 1}, "valid_key.*must be a string"),
        ({"valid_key": "x" * 8_193}, "valid_key.*8192 UTF-8 bytes"),
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
