"""Refusal and evidence-policy tests for continuation replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.history.chat import build_fork_injected_history
from sase.history.chat_fork.build import build_fork_injected_history as build_fork
from sase.history.chat_fork.continuation import (
    ContinuationReplayRefusal,
    ContinuationSourceError,
    replay_versioned_continuation_history,
)
from tests.history._continuation_replay_hydration_helpers import (
    agent_member,
    monitor_member,
    publish_agent_delta,
    publish_monitor,
    write_agent_node,
    write_json,
    write_monitor_result_node,
)


def test_legacy_none_policy_reports_conflict_for_raw_monitor_logs(
    tmp_path: Path,
) -> None:
    monitor = tmp_path / "artifacts" / "20260911010202"
    monitor.mkdir(parents=True)
    write_json(
        monitor / "agent_meta.json",
        {
            "name": "acme--mon",
            "monitor_next_output": "none",
        },
    )
    current = tmp_path / "artifacts" / "20260911010303"
    write_agent_node(
        current,
        name="acme--1",
        node_id="agent-delta-current",
        prompt="Continue after the monitor.",
        response="CURRENT_REPLY",
    )
    log_path = tmp_path / "monitor.log"
    log_path.write_text("SECRET_MONITOR_TAIL\n# New Query\n", encoding="utf-8")
    source = {
        "kind": "session",
        "name": "acme",
        "members": [
            {
                **monitor_member(
                    monitor, next_output="none", log_tail="SECRET_MONITOR_TAIL\n"
                ),
                "path": str(log_path),
            },
            agent_member(tmp_path, "20260911010303", "acme--1"),
        ],
        "excluded": [],
    }

    rendered = build_fork_injected_history([source])
    result = replay_versioned_continuation_history([source])
    assert result is not None
    assert "CURRENT_REPLY" in rendered
    assert "Opaque Legacy Boundary" in rendered
    assert "SECRET_MONITOR_TAIL" not in rendered
    kinds = {omission.get("kind") for omission in result.manifest.get("omissions", [])}
    assert "legacy_evidence_policy_conflict" not in kinds


def test_missing_parent_blocks_automatic_launch(tmp_path: Path) -> None:
    child = tmp_path / "artifacts" / "20260911010202"
    write_agent_node(
        child,
        name="acme--1",
        node_id="agent-delta-child",
        parents=["agent-delta-missing"],
        prompt="Continue from a missing source.",
        response="CHILD_REPLY",
    )
    source = agent_member(tmp_path, "20260911010202", "acme--1")
    rendered = build_fork_injected_history([source])
    assert "`missing_parent`" in rendered
    with pytest.raises(ContinuationReplayRefusal) as exc:
        build_fork([source], automatic=True)
    assert exc.value.kind == "missing_parent"


def test_failed_starter_without_checkpoint_is_nonlaunchable(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    starter = artifacts / "20260911010101"
    monitor = artifacts / "20260911010202"
    published = publish_agent_delta(
        tmp_path,
        starter,
        name="acme--0",
        prompt="Start the monitor.",
        response="",
        status="failed",
    )
    publish_monitor(
        monitor,
        parents=[published.node_id],
        starter_artifacts_dir=starter,
        status="failed",
        exit_code=1,
    )
    source = monitor_member(monitor)
    result = replay_versioned_continuation_history([source])
    assert result is not None
    assert any(
        refusal.kind == "failed_starter_without_checkpoint"
        for refusal in result.refusals
    )
    with pytest.raises(ContinuationReplayRefusal) as exc:
        build_fork([source], automatic=True)
    assert exc.value.kind == "failed_starter_without_checkpoint"


def test_digest_mismatch_is_explicit_missing_source(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    base = artifacts / "20260911010101"
    child = artifacts / "20260911010202"
    write_agent_node(
        base,
        name="acme--0",
        node_id="agent-delta-base",
        prompt="Keep the base.",
        response="BASE_REPLY",
    )
    node_path = base / "continuation" / "nodes" / "agent-delta-base.json"
    node = json.loads(node_path.read_text(encoding="utf-8"))
    node["content_sha256"] = "b" * 64
    node_path.write_text(
        json.dumps(node, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_agent_node(
        child,
        name="acme--1",
        node_id="agent-delta-child",
        parents=["agent-delta-base"],
        prompt="Continue.",
        response="CHILD_REPLY",
    )
    source = agent_member(tmp_path, "20260911010202", "acme--1")
    result = replay_versioned_continuation_history([source])
    assert result is not None
    kinds = {omission.get("kind") for omission in result.manifest.get("omissions", [])}
    assert "digest_mismatch" in kinds or "missing_parent" in kinds
    with pytest.raises(ContinuationReplayRefusal):
        build_fork([source], automatic=True)


def test_historical_agent_session_monitor_records_prefix_reset(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    older = artifacts / "20260911010101"
    newer = artifacts / "20260911010202"
    write_monitor_result_node(older, next_output="tail")
    write_monitor_result_node(newer, next_output="tail")
    source = {
        "kind": "session",
        "name": "acme",
        "members": [
            monitor_member(older, name="acme--old"),
            monitor_member(newer, name="acme--new"),
        ],
        "excluded": [],
    }
    result = replay_versioned_continuation_history([source])
    assert result is not None
    assert result.manifest.get("prefix_reset_reason")
    assert "Prefix reset" in result.rendered


def test_legacy_mixed_protected_and_raw_none_policy_conflicts(
    tmp_path: Path,
) -> None:
    from sase.history.chat_fork.continuation._render import prepare_legacy_payload

    payload, omission = prepare_legacy_payload(
        {
            "label": "legacy",
            "protected_text": "USER_GATE_INSTRUCTION\nSECRET_LOG",
            "may_contain_raw_evidence": True,
            "has_protected_user_content": True,
        },
        evidence_policy="none",
    )
    assert payload.get("legacy_evidence_policy_conflict") is True
    assert "protected_text" not in payload
    assert omission is not None
    assert omission["kind"] == "legacy_evidence_policy_conflict"


def test_unknown_parent_still_refuses_automatic_launch(tmp_path: Path) -> None:
    child = tmp_path / "artifacts" / "20260911010202"
    write_agent_node(
        child,
        name="acme--1",
        node_id="agent-delta-child",
        parents=["agent-delta-missing"],
        prompt="Continue from a missing source.",
        response="CHILD_REPLY",
    )
    source = agent_member(tmp_path, "20260911010202", "acme--1")
    result = replay_versioned_continuation_history([source])

    assert result is not None
    assert any(refusal.kind == "missing_parent" for refusal in result.refusals)


def test_cross_run_archived_node_is_not_spliced(tmp_path: Path) -> None:
    run_dir = tmp_path / "artifacts" / "20260911010202"
    archived_nodes = run_dir / "attempts" / "01" / "continuation" / "nodes"
    archived_nodes.mkdir(parents=True)
    write_json(
        archived_nodes / "agent-delta-foreign.json",
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "node_id": "agent-delta-foreign",
            "kind": "agent_delta",
            "parent_ids": [],
            "owner": {
                "project": "proj",
                "run_id": "20260911010101",
                "agent_name": "acme--0",
            },
            "content_ref": "local:continuation/records/agent_delta/foreign.json",
            "content_sha256": "0" * 64,
        },
    )
    write_agent_node(
        run_dir,
        name="acme--1",
        node_id="agent-delta-child",
        parents=["agent-delta-foreign"],
        prompt="Continue from a missing source.",
        response="CHILD_REPLY",
    )

    source = agent_member(tmp_path, "20260911010202", "acme--1")
    result = replay_versioned_continuation_history([source])

    assert result is not None
    assert any(refusal.kind == "missing_parent" for refusal in result.refusals)


def test_portable_file_ref_resolves_with_digest_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.artifact_file_types import ArtifactFile
    from sase.history.chat_fork.continuation._refs import read_json_ref

    payload = {"schema_version": 1, "kind": "portable", "value": "ok"}
    stored = tmp_path / "portable.json"
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    stored.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    artifact = ArtifactFile(
        id="explicit-portable-1",
        label="portable continuation node",
        kind="file",
        path=str(stored),
        explicit=True,
        sha256=digest,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_facade.read_artifact_file_index",
        lambda *args, **kwargs: [artifact],
    )
    loaded = read_json_ref(
        tmp_path,
        "file:explicit-portable-1",
        expected_sha256=digest,
    )
    assert loaded["value"] == "ok"
    with pytest.raises(ContinuationSourceError):
        read_json_ref(
            tmp_path,
            "file:explicit-portable-1",
            expected_sha256="a" * 64,
        )
