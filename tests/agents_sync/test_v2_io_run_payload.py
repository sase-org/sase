from __future__ import annotations

import pytest

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_io import _hood_snapshot_from_json
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
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
