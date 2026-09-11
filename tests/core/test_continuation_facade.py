"""Tests for the Rust-backed continuation facade."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

import pytest

from sase.core.continuation_facade import (
    bind_conditional_completion,
    continuation_wire_schema_version,
    plan_continuation_budget,
    plan_continuation_replay,
    preview_conditional_completion,
    resolve_continuation_policy,
    rollback_conditional_completion_binding,
    seal_conditional_completion,
    select_continuation_evidence,
    validate_continuation_delivery_record,
    validate_continuation_graph,
    validate_continuation_intent,
    validate_continuation_node,
    validate_diagnostic_manifest,
    validate_launch_requester_continuation,
    validate_monitor_result,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION

_SHA = "a" * 64


def _owner() -> dict[str, str]:
    return {
        "project": "sase",
        "run_id": "run-1",
        "agent_name": "agent-1",
        "machine_name": "athena",
    }


def _node(
    node_id: str,
    parents: list[str] | None = None,
    *,
    kind: str = "agent_delta",
) -> dict[str, Any]:
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "node_id": node_id,
        "kind": kind,
        "parent_ids": parents or [],
        "owner": _owner(),
        "content_ref": f"file:explicit:{node_id}",
        "content_sha256": _SHA,
    }


def _monitor_result(
    outcome: str = "failed",
    *,
    exit_code: int | None = 1,
) -> dict[str, Any]:
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "result_id": "result-1",
        "monitor_id": "monitor-1",
        "starter_execution_id": "run-1",
        "outcome": outcome,
        "exit_code": exit_code,
        "command": ["just", "check"],
        "cwd": "/workspace/sase",
        "started_at": "2026-09-11T12:00:00Z",
        "ended_at": "2026-09-11T12:01:00Z",
        "elapsed_ms": 60_000,
        "workspace_identity": "workspace-1",
        "diagnostic_manifest_ref": "file:explicit:diagnostics",
        "retained_log": {
            "log_ref": "file:explicit:monitor-log",
            "local_locator": "logs/monitor.log",
            "total_observed_bytes": 4096,
            "retained_ranges": [{"start": 0, "end": 4096}],
            "complete": True,
            "drain_confirmed": True,
        },
    }


def _diagnostic_manifest() -> dict[str, Any]:
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "producer": "monitor-1",
        "complete": True,
        "manifest_ref": "file:explicit:diagnostics",
        "stages": [
            {
                "stage_id": "pytest",
                "name": "pytest",
                "status": "failed",
                "exit_code": 1,
                "diagnostic_refs": ["file:explicit:pytest-log"],
                "counts": {"failures": 1},
            }
        ],
    }


def test_schema_version_matches_rust_binding() -> None:
    assert continuation_wire_schema_version() == CONTINUATION_WIRE_SCHEMA_VERSION


def test_node_intent_monitor_manifest_and_delivery_validation_round_trip() -> None:
    assert validate_continuation_node(_node("root"))["node_id"] == "root"

    intent = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "intent_id": "intent-1",
        "next_action": "Continue from the retained monitor result.",
        "route": {"inherit_model": True, "inherit_effort": True},
        "outcome_policy_ref": "file:explicit:policy",
        "conditional_completion_ref": "file:explicit:completion",
    }
    assert validate_continuation_intent(intent)["intent_id"] == "intent-1"

    result = _monitor_result("completed", exit_code=0)
    assert validate_monitor_result(result)["outcome"] == "completed"

    manifest = _diagnostic_manifest()
    assert validate_diagnostic_manifest(manifest)["stages"][0]["stage_id"] == "pytest"

    delivery = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "key": {
            "monitor_id": "monitor-1",
            "result_id": "result-1",
            "branch": "failed",
        },
        "selected_action": "continue",
        "reserved_identity": "agent-1",
        "attempt_history": [
            {
                "attempt_id": "attempt-1",
                "status": "acknowledged",
                "recorded_at": "2026-09-11T12:02:00Z",
                "detail": "queued successor",
            }
        ],
        "acknowledged_by": "agent-1",
        "disposition": "acknowledged",
        "disposition_reason": "successor launch acknowledged by host",
    }
    assert (
        validate_continuation_delivery_record(delivery)["disposition"] == "acknowledged"
    )

    launch_continuation = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "mode": "resume_requester",
        "required": True,
        "checkpoint": "Continue the phase after helper approval.",
        "context": {
            "SASE_AGENT_NAME": "agent--0",
            "SASE_BEAD_ID": "sase-1.2",
        },
        "resume_branches": ["approve", "reject", "timeout", "failed"],
        "terminal_branches": ["stopped"],
    }
    assert (
        validate_launch_requester_continuation(launch_continuation)["mode"]
        == "resume_requester"
    )


def test_unknown_node_kind_and_schema_version_raise_value_error() -> None:
    bad_kind = _node("bad", kind="bogus")
    with pytest.raises(ValueError, match="unknown variant"):
        validate_continuation_node(bad_kind)

    bad_version = _node("bad-version")
    bad_version["schema_version"] = 99
    with pytest.raises(ValueError, match="unsupported"):
        validate_continuation_node(bad_version)


def test_graph_validation_summarizes_duplicates_and_missing_parents() -> None:
    summary = validate_continuation_graph(
        [
            _node("root"),
            _node("root"),
            _node("leaf", ["root", "missing-parent"]),
        ]
    )

    assert summary["schema_version"] == CONTINUATION_WIRE_SCHEMA_VERSION
    assert summary["node_count"] == 3
    assert summary["edge_count"] == 2
    assert summary["duplicate_ids"] == ["root"]
    assert summary["missing_parent_ids"] == ["missing-parent"]


def test_replay_planning_is_parent_first_and_reports_shared_ancestry() -> None:
    request = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "records": [
            _node("leaf-left", ["base"]),
            _node("base"),
            _node("leaf-right", ["base"]),
        ],
        "root_ids": ["leaf-left", "leaf-right", "missing-root"],
        "selected_evidence_refs": ["file:explicit:diagnostics"],
        "rendered_components": [
            {"name": "local_prompt", "utf8_bytes": 100},
            {"name": "selected_evidence", "utf8_bytes": 25},
        ],
        "checkpoint_coverage": [
            {
                "checkpoint_ref": "file:explicit:checkpoint",
                "covered_node_ids": ["base"],
            }
        ],
    }

    plan = plan_continuation_replay(request)

    assert plan["ordered_node_ids"] == ["base", "leaf-left", "leaf-right"]
    assert [block["node_id"] for block in plan["stable_blocks"]] == [
        "base",
        "leaf-left",
        "leaf-right",
    ]
    assert all(
        block["block_id"].startswith("block:v1:") for block in plan["stable_blocks"]
    )
    assert plan["selected_evidence_refs"] == ["file:explicit:diagnostics"]
    assert plan["rendered_component_sizes"]["total_utf8_bytes"] == 125
    assert plan["checkpoint_coverage"][0]["covered_node_ids"] == ["base"]
    assert plan["omissions"] == [
        {
            "kind": "missing_root",
            "node_id": "missing-root",
            "parent_id": None,
            "reason": "root id has no continuation record",
        }
    ]
    assert any(
        entry["node_id"] == "base" and entry["reused"] is True
        for entry in plan["branch_attribution"]
    )


def test_replay_rejects_conflicting_duplicates_and_cycles() -> None:
    conflicting = _node("same")
    conflicting["content_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="conflicting duplicate"):
        plan_continuation_replay(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "records": [_node("same"), conflicting],
                "root_ids": ["same"],
            }
        )

    with pytest.raises(ValueError, match="cycle"):
        plan_continuation_replay(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "records": [_node("left", ["right"]), _node("right", ["left"])],
                "root_ids": ["left"],
            }
        )


def test_evidence_policies_are_outcome_aware_and_never_embed_strict_file_refs() -> None:
    failed = select_continuation_evidence(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "result": _monitor_result(),
            "policy": "auto",
            "diagnostic_manifest": _diagnostic_manifest(),
        }
    )
    assert failed["context_kind"] == "failed_diagnostics"
    assert failed["include_raw_excerpt"] is False
    assert failed["diagnostic_stage_ids"] == ["pytest"]
    assert "file:explicit:pytest-log" in failed["selected_refs"]

    file_only = select_continuation_evidence(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "result": _monitor_result(),
            "policy": "file",
        }
    )
    none = select_continuation_evidence(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "result": _monitor_result(),
            "policy": "none",
        }
    )

    assert file_only["include_raw_excerpt"] is False
    assert file_only["context_kind"] == "file_refs"
    assert none["include_raw_excerpt"] is False
    assert none["context_kind"] == "retrieval_only"


def test_policy_resolution_and_budget_decisions_are_typed() -> None:
    completed = resolve_continuation_policy(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "outcome": "completed",
            "profile": "verify",
            "prepared_completion_ref": "file:explicit:completion",
        }
    )
    assert completed["action"] == "complete"
    assert completed["completion_ref"] == "file:explicit:completion"
    assert completed["launchable"] is False

    failed = resolve_continuation_policy(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "outcome": "failed",
            "profile": "verify",
            "inherited_model": "gpt-5-codex",
            "inherited_effort": "high",
        }
    )
    assert failed["action"] == "continue"
    assert failed["launchable"] is True
    assert failed["model"] == "gpt-5-codex"
    assert failed["effort"] == "high"

    budget = plan_continuation_budget(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "rendered_prompt_bytes": 900,
            "essential_bytes": 300,
            "provider_budget": {
                "context_limit_bytes": 650,
                "transport_limit_bytes": 800,
                "instruction_reserve_bytes": 100,
            },
            "reduction_candidates": [
                {"kind": "checkpoint", "bytes": 400},
                {"kind": "identity_deduplication", "bytes": 100},
                {"kind": "newest_diagnostics", "bytes": 350},
            ],
        }
    )
    assert budget["kind"] == "compact"
    assert [item["kind"] for item in budget["reductions"]] == [
        "identity_deduplication",
        "newest_diagnostics",
    ]
    assert budget["estimated_prompt_bytes"] == 450

    refusal_request = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "rendered_prompt_bytes": 900,
        "essential_bytes": 700,
        "provider_budget": {
            "context_limit_bytes": 650,
            "instruction_reserve_bytes": 100,
        },
    }
    refusal = plan_continuation_budget(refusal_request)
    assert refusal["kind"] == "refuse"
    assert "essential_content_exceeds_budget" in refusal["reasons"]


def _digest(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def _prepare_request(**overrides: object) -> dict[str, Any]:
    request: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "creator": {
            "project": "sase",
            "run_id": "run-1",
            "agent_name": "agent-1",
        },
        "context": {
            "run_id": "run-1",
            "agent_id": "agent-1",
            "turn_nonce": "nonce-1",
            "plan_digest": _digest("plan"),
            "context_digest": _digest("context"),
            "obligation_ids": ["repo-main"],
        },
        "success_message": "Required checks passed in {duration}.",
        "verification_command": ["just", "check-full"],
        "declaration": {
            "schema_version": 2,
            "context_digest": _digest("context"),
            "plan_digest": _digest("plan"),
            "payloads": [
                {
                    "instance_id": "commit",
                    "payload": {
                        "repositories": [
                            {
                                "repo_id": "repo-main",
                                "action": "commit",
                                "message": "fix: finish the change",
                            }
                        ],
                        "deferrals": [],
                    },
                }
            ],
        },
        "observations": [
            {
                "repo_id": "repo-main",
                "kind": "main",
                "name": "main",
                "head": _digest("head"),
                "head_tree": _digest("head-tree"),
                "index_tree": _digest("index-tree"),
                "complete": True,
                "paths": [
                    {
                        "path": "src/app.py",
                        "xy": "M",
                        "content_hash": _digest("app"),
                        "mode": "100644",
                        "kind": "file",
                        "protected": False,
                        "foreign": False,
                    }
                ],
            }
        ],
        "executors": [
            {
                "instance_id": "commit",
                "provider_ref": "builtin@commit",
                "headless": True,
                "durable_replay": True,
                "requires_model": False,
            }
        ],
    }
    request.update(overrides)
    return request


def test_conditional_completion_seal_preview_and_single_use_bind() -> None:
    intent = seal_conditional_completion(_prepare_request())
    assert intent["status"] == "prepared"
    assert intent["verification"]["level"] == "check_full"
    preview = preview_conditional_completion(intent)
    assert preview["success_action"] == "complete"
    assert preview["eligible"] is True

    bound = bind_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": intent,
            "monitor_id": "monitor-1",
            "command": ["just", "check-full"],
            "request_fingerprint": "sha256:abc",
        }
    )
    assert bound["status"] == "bound"
    with pytest.raises(ValueError, match="not reusable"):
        bind_conditional_completion(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "intent": bound,
                "monitor_id": "monitor-2",
                "command": ["just", "check-full"],
                "request_fingerprint": "sha256:def",
            }
        )
    restored = rollback_conditional_completion_binding(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": bound,
            "monitor_id": "monitor-1",
        }
    )
    assert restored["status"] == "prepared"


def test_conditional_completion_rejects_missing_decisions_and_changed_commands() -> (
    None
):
    request = _prepare_request()
    request["declaration"]["payloads"][0]["payload"]["repositories"] = []
    with pytest.raises(ValueError, match="missing repository decisions"):
        seal_conditional_completion(request)

    intent = seal_conditional_completion(_prepare_request())
    with pytest.raises(ValueError, match="does not match"):
        bind_conditional_completion(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "intent": intent,
                "monitor_id": "monitor-1",
                "command": ["just", "check"],
                "request_fingerprint": "sha256:abc",
            }
        )
