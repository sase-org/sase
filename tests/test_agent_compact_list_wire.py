"""Decode contract tests for the compact agent list wire.

These tests pin the Python side of the additive compact contract: the
schema-version gate, the ``meta``/``workflow``/``record_shape=compact``
key mapping (never the full ``agent_meta``/``workflow_state`` spellings),
marker-presence semantics, and the shared nested-reader bridging for
session turns and finalizer summaries. They run without the new Rust
list bindings by decoding hand-written payloads shaped like the
``sase-core`` projection output.
"""

from __future__ import annotations

import pytest

from sase.core.agent_scan_list_conversion import (
    SUPPORTED_AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSIONS,
    agent_artifact_list_index_query_to_dict,
    agent_artifact_list_records_from_dicts,
    agent_artifact_list_scan_wire_from_dict,
)
from sase.core.agent_scan_list_wire import (
    AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION,
    AgentArtifactListSnapshotWire,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    agent_artifact_index_query_to_dict,
)


def _minimal_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "project_name": "home",
        "project_dir": "/tmp/x/home",
        "project_file": "/tmp/x/home/home.sase",
        "workflow_dir_name": "ace-run",
        "artifact_dir": "/tmp/x/home/artifacts/ace-run/20261117120000",
        "timestamp": "20261117120000",
        "has_done_marker": True,
        "record_shape": "compact",
    }
    record.update(overrides)
    return record


def _minimal_snapshot(**overrides: object) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "schema_version": AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION,
        "projects_root": "/tmp/x",
        "options": {},
        "stats": {},
        "records": [_minimal_record()],
    }
    snapshot.update(overrides)
    return snapshot


def test_schema_version_gate_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="schema mismatch"):
        agent_artifact_list_scan_wire_from_dict(_minimal_snapshot(schema_version=99))


def test_record_shape_gate_rejects_full_shape() -> None:
    record = _minimal_record(record_shape="full")
    with pytest.raises(ValueError, match="unexpected shape"):
        agent_artifact_list_records_from_dicts([record])


def test_compact_keys_decode_without_full_markers() -> None:
    record = _minimal_record(
        meta={"name": "bob", "cl_name": "cl1"},
        done={"outcome": "completed", "cl_name": "cl1"},
        workflow={"workflow_name": "w", "status": "done", "steps": []},
        plan_path="/tmp/p.md",
        prompt_steps=[
            {
                "file_name": "a.json",
                "step_name": "s",
                "step_type": "agent",
                "status": "done",
            }
        ],
    )
    (decoded,) = agent_artifact_list_records_from_dicts([record])
    assert decoded.record_shape == "compact"
    assert decoded.meta is not None and decoded.meta.name == "bob"
    assert decoded.done is not None and decoded.done.outcome == "completed"
    assert decoded.workflow is not None and decoded.workflow.workflow_name == "w"
    assert decoded.plan_path == "/tmp/p.md"
    assert len(decoded.prompt_steps) == 1
    # The compact dataclasses expose no full-record spellings at all.
    assert not hasattr(decoded, "agent_meta")
    assert not hasattr(decoded, "workflow_state")
    assert not hasattr(decoded, "raw_prompt_snippet")


def test_none_vs_empty_preserved() -> None:
    record = _minimal_record(
        meta={"wait_for": [], "plan_submitted_at": []},
        waiting={"waiting_for": []},
    )
    (decoded,) = agent_artifact_list_records_from_dicts([record])
    assert decoded.meta is not None
    assert decoded.meta.wait_for == []
    assert decoded.waiting is not None
    assert decoded.waiting.waiting_for == []
    assert decoded.meta.tribe is None
    assert decoded.done is None
    assert decoded.running is None
    assert decoded.pending_question is None


def test_unknown_keys_are_ignored() -> None:
    record = _minimal_record(
        meta={"name": "bob", "some_future_field": {"nested": [1, 2]}},
        some_future_record_field=[1, 2, 3],
    )
    (decoded,) = agent_artifact_list_records_from_dicts([record])
    assert decoded.meta is not None and decoded.meta.name == "bob"


def test_output_facts_keep_meta_and_diff_path() -> None:
    record = _minimal_record(
        done={
            "outcome": "completed",
            "step_output": {
                "meta": {"meta_commit_message": "keep"},
                "diff_path": "/tmp/keep.diff",
            },
        },
        prompt_steps=[
            {
                "file_name": "a.json",
                "step_name": "s",
                "step_type": "agent",
                "status": "done",
                "output": {"meta": {"meta_prompt": "keep"}},
            }
        ],
    )
    (decoded,) = agent_artifact_list_records_from_dicts([record])
    assert decoded.done is not None and decoded.done.step_output is not None
    assert decoded.done.step_output.meta == {"meta_commit_message": "keep"}
    assert decoded.done.step_output.diff_path == "/tmp/keep.diff"
    assert decoded.prompt_steps[0].output is not None
    assert decoded.prompt_steps[0].output.meta == {"meta_prompt": "keep"}


def test_turn_bridges_to_shared_nested_reader() -> None:
    record = _minimal_record(
        meta={
            "agent_session_turn": {
                "kind": "monitor",
                "id": "m1",
                "state": "running",
                "stop_status": "MONITORED",
                "followup_outcome": "done",
                "host_completion_status": "ok",
                "monitor": {"exit_code": 0},
            }
        },
    )
    (decoded,) = agent_artifact_list_records_from_dicts([record])
    assert decoded.meta is not None
    turn = decoded.meta.agent_session_turn
    assert turn is not None and turn.kind == "monitor" and turn.id == "m1"
    assert turn.monitor is not None and turn.monitor.exit_code == 0
    # Deferred turn detail degrades to None instead of failing the decode.
    assert turn.monitor.command is None
    assert turn.followup_outcome == "done"


def test_finalizer_bridges_with_existing_caps() -> None:
    instances = [
        {"id": f"i{n}", "status": "running", "op": "declare", "step": "s"}
        for n in range(20)
    ]
    record = _minimal_record(
        meta={
            "finalizer_status": {
                "phase": "executing",
                "status": "running",
                "updated_at": 1.5,
                "instance_count": 20,
                "instances": instances,
            }
        },
    )
    (decoded,) = agent_artifact_list_records_from_dicts([record])
    assert decoded.meta is not None
    summary = decoded.meta.finalizer_status
    assert summary is not None and summary.phase == "executing"
    assert len(summary.instances) == 16
    assert summary.instances[0].id == "i0"


def test_snapshot_envelope_decodes() -> None:
    snapshot = agent_artifact_list_scan_wire_from_dict(
        _minimal_snapshot(
            index_window={"requested_limit": 50, "returned_record_count": 1},
            clan_context=[{"agent_clan": "c", "clan_tribe": "chop"}],
            index_completeness={"complete_history": True},
        )
    )
    assert isinstance(snapshot, AgentArtifactListSnapshotWire)
    assert snapshot.projects_root == "/tmp/x"
    assert snapshot.index_window is not None
    assert snapshot.index_window.returned_record_count == 1
    assert len(snapshot.clan_context) == 1
    assert snapshot.clan_context[0].clan_tribe == "chop"
    assert snapshot.index_completeness is not None
    assert snapshot.index_completeness.complete_history is True


def test_query_dict_matches_full_query_shape() -> None:
    query = AgentArtifactIndexQueryWire(
        include_full_history=True,
        record_shape="list",
        agents_list_projection=True,
    )
    assert agent_artifact_list_index_query_to_dict(query) == (
        agent_artifact_index_query_to_dict(query)
    )
    assert set(SUPPORTED_AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSIONS) == {1}
