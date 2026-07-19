"""Python facade coverage for the Rust axe chop engine."""

from __future__ import annotations

import json

import pytest

from sase.core.axe_chop_facade import (
    CHOP_ENGINE_SCHEMA_VERSION,
    CHOP_RESULT_SCHEMA_VERSION,
    CHOP_STATE_SCHEMA_VERSION,
    apply_chop_checkpoint_update,
    check_and_record_chop_once_per,
    derive_chop_agent_name,
    evaluate_chop_decision,
    expand_chop_targets,
    parse_chop_duration,
    parse_chop_result,
    validate_axe_config,
    validate_chop_proposal,
)
from sase.core.rust import require_rust_binding


def test_result_contract_round_trips_through_rust() -> None:
    result = parse_chop_result(
        json.dumps(
            {
                "schema_version": 1,
                "status": "ok",
                "summary": "found work",
                "counters": {"findings": 1},
                "proposed_launches": [
                    {
                        "id": "fix",
                        "prompt": "Fix the finding.\n#pr",
                        "workspace": "gh:sase-org/sase",
                    }
                ],
            }
        )
    )

    assert result["schema_version"] == 1
    assert result["status"] == "ok"
    assert result["proposed_launches"][0]["id"] == "fix"
    assert result["proposed_launches"][0]["env"] == {}


def test_proposal_validation_rejects_standalone_workflow_reference() -> None:
    with pytest.raises(ValueError, match="workflow_reference_forbidden"):
        validate_chop_proposal(
            {
                "prompt": "#!retired_workflow",
                "workspace": "git:sase",
            }
        )


def test_decision_and_bookkeeping_facades() -> None:
    decision = evaluate_chop_decision(
        {
            "schema_version": 1,
            "trigger": {
                "provider": "git.commits_since",
                "project": "sase",
                "threshold": 2,
                "checkpoint_policy": "on_action_accepted",
            },
            "git": [
                {
                    "project": "sase",
                    "head": "abc",
                    "commits_since_checkpoint": 3,
                    "checkpoint_found": True,
                }
            ],
            "now": "2026-07-18T12:00:00Z",
        }
    )
    assert decision["outcome"] == "fire"
    assert decision["checkpoint_cursor"] == "abc"

    document = apply_chop_checkpoint_update(
        {
            "schema_version": 1,
            "document": {"schema_version": 1, "entries": {}},
            "key": decision["checkpoint_key"],
            "cursor": decision["checkpoint_cursor"],
            "now": "2026-07-18T12:00:00Z",
            "policy": decision["checkpoint_policy"],
            "event": "action_accepted",
        }
    )
    assert document["entries"]["git.commits_since:sase"]["cursor"] == "abc"

    accepted = check_and_record_chop_once_per(
        {
            "schema_version": 1,
            "document": {"schema_version": 1, "entries": []},
            "key": "event:abc",
            "now": "2026-07-18T12:00:00Z",
            "capacity": 10,
        }
    )
    assert accepted["outcome"] == "accept"


def test_target_duration_and_agent_name_facades() -> None:
    expansion = expand_chop_targets(
        {
            "schema_version": 1,
            "chop_name": "refresh_docs",
            "for_each": [
                {
                    "name": "sase-core",
                    "overrides": {"run_every": "1h30m"},
                }
            ],
        }
    )
    assert expansion["instances"][0]["instance_id"] == ("refresh_docs[sase-core]")
    assert expansion["instances"][0]["overrides"] == {"run_every": "1h30m"}
    assert parse_chop_duration("1d2h") == 93_600
    assert (
        derive_chop_agent_name(
            "refresh_docs",
            target_key="sase-core",
            proposal_index=0,
            run_token="20260719T072506_123456",
        )
        == "chop.refresh_docs.sase-core.6_123456.1"
    )
    assert (
        derive_chop_agent_name("refresh_docs", target_key="sase-core")
        == "chop.refresh_docs.sase-core.1"
    )

    long_chop = "very-long-chop_" * 12
    long_target = "very-long-target_" * 12
    first_bounded = derive_chop_agent_name(
        long_chop,
        target_key=long_target,
        proposal_index=0,
        run_token="20260719T072506_123456",
    )
    second_bounded = derive_chop_agent_name(
        long_chop,
        target_key=long_target,
        proposal_index=1,
        run_token="20260719T072507_654321",
    )
    assert len(first_bounded) <= 120
    assert len(second_bounded) <= 120
    assert first_bounded.endswith(".6_123456.1")
    assert second_bounded.endswith(".7_654321.2")
    assert first_bounded != second_bounded


def test_strict_config_diagnostics_preserve_provenance() -> None:
    diagnostics = validate_axe_config(
        {
            "lumberjacks": {
                "bad": {
                    "interval": 0,
                    "chops": [{"name": "audit", "xprompt": "#!audit"}],
                }
            }
        },
        provenance={"lumberjacks.bad": "overlay:athena"},
    )
    assert {item["code"] for item in diagnostics} >= {
        "agent_chop_removed",
        "non_positive_integer",
    }
    assert {item["layer"] for item in diagnostics} == {"overlay:athena"}


def test_schema_versions_match_the_facade_contract() -> None:
    for binding_name, expected in [
        ("chop_engine_schema_version", CHOP_ENGINE_SCHEMA_VERSION),
        ("chop_result_schema_version", CHOP_RESULT_SCHEMA_VERSION),
        ("chop_state_schema_version", CHOP_STATE_SCHEMA_VERSION),
    ]:
        assert require_rust_binding(binding_name)() == expected
