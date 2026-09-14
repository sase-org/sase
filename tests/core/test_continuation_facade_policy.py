"""Tests for continuation evidence selection, policy resolution, and budgeting."""

from __future__ import annotations

from sase.core.continuation_facade import (
    freeze_continuation_policy,
    plan_continuation_budget,
    resolve_continuation_policy,
    select_continuation_evidence,
    validate_continuation_policy,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from tests.core._continuation_facade_helpers import (
    make_diagnostic_manifest,
    make_monitor_result,
)


def test_evidence_policies_are_outcome_aware_and_never_embed_strict_file_refs() -> None:
    failed = select_continuation_evidence(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "result": make_monitor_result(),
            "policy": "auto",
            "diagnostic_manifest": make_diagnostic_manifest(),
        }
    )
    assert failed["context_kind"] == "failed_diagnostics"
    assert failed["include_raw_excerpt"] is False
    assert failed["diagnostic_stage_ids"] == ["pytest"]
    assert "file:explicit:pytest-log" in failed["selected_refs"]

    file_only = select_continuation_evidence(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "result": make_monitor_result(),
            "policy": "file",
        }
    )
    none = select_continuation_evidence(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "result": make_monitor_result(),
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

    none_despite_shared = resolve_continuation_policy(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "outcome": "completed",
            "shared_next": "shared follow-up",
            "explicit_policy": {
                "completed": {"action": "none"},
                "failed": {
                    "action": "continue",
                    "next_action": "repair the failure",
                    "model": "opus@high",
                },
                "timeout": {"action": "none"},
            },
        }
    )
    assert none_despite_shared["action"] == "none"
    assert none_despite_shared["launchable"] is False

    frozen = freeze_continuation_policy(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "shared_next": "shared follow-up",
            "explicit_policy": {
                "completed": {"action": "none"},
                "failed": {
                    "action": "continue",
                    "next_action": "repair the failure",
                    "model": "opus@high",
                },
                "timeout": {"action": "none"},
            },
        }
    )
    assert frozen["fingerprint"].startswith("sha256:")
    assert frozen["branches"]["completed"]["action"] == "none"
    assert frozen["branches"]["failed"]["action"] == "continue"
    assert frozen["branches"]["failed"]["model"] == "opus"
    assert frozen["branches"]["failed"]["effort"] == "high"
    assert frozen["branches"]["stopped"]["action"] == "none"
    assert frozen["branches"]["lost"]["action"] == "none"
    validated = validate_continuation_policy(
        frozen["explicit_policy"]
        or {
            "completed": {"action": "none"},
            "failed": {"action": "none"},
            "timeout": {"action": "none"},
        }
    )
    assert validated["completed"]["action"] == "none"

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
