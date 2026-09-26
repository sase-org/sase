"""Branch-keyed gate-shell follow-up policy resolution."""

from __future__ import annotations

from typing import Any, cast

import pytest

from sase.gate_turn.models import GateTurnState
from sase.gate_turn.followup_policy import (
    _settlement_branch_key as settlement_branch_key,
)
from sase.gate_turn.followup_policy import (
    resolve_gate_branch_presentation,
    resolve_gate_followup,
    shell_block_unparseable,
)
from sase.notification_gates.model_turn import GateTurnSpec, subset_branches_allowed
from sase.plan_chain import PLAN_CHAIN_CODER_SUFFIX
from sase.plan_gate import PlanGateTier
from sase.plan_gate_turn.create import plan_gate_turn_block
from sase.question_gate_turn.create import _question_gate_turn_spec


def _envelope(
    turn: dict[str, Any], branches: list[list[str]] | None = None
) -> dict[str, Any]:
    return {
        "turn": turn,
        "branches": branches if branches is not None else [["a"], ["b"]],
        "gate_timeout_seconds": 3600.0,
    }


def _response(*option_ids: str) -> dict[str, Any]:
    return {"selected_option_ids": list(option_ids)}


def _tale_envelope() -> dict[str, Any]:
    return {
        "kind": "plan",
        "turn": plan_gate_turn_block("tale"),
        "branches": [["approve", "commit"], ["reject"], ["feedback"]],
        "gate_timeout_seconds": 86400.0,
    }


def _question_gate_turn_request() -> dict[str, Any]:
    return _question_gate_turn_spec(
        [
            {
                "question": "Which database?",
                "options": [{"label": "SQLite"}, {"label": "PostgreSQL"}],
            }
        ],
        session_id="round-1",
        base_prompt="Implement the feature.",
        prior_rounds=[],
    )


def _assert_settlement_accepts_created_shell_branches(
    *,
    kind: str,
    turn: dict[str, Any],
    branches: tuple[tuple[str, ...], ...],
    creation_parsed: GateTurnSpec,
) -> None:
    envelope = {
        "kind": kind,
        "turn": turn,
        "branches": [list(branch) for branch in branches],
    }
    assert shell_block_unparseable(envelope) is False
    for branch_key, branch in creation_parsed.branches.items():
        if branch_key in {"timeout", "stopped", "failed"}:
            gate_state = cast(GateTurnState, branch_key)
            response = {}
        else:
            gate_state = "answered"
            response = _response(*branch_key.split("+"))
        assert resolve_gate_branch_presentation(
            envelope,
            gate_state=gate_state,
            response=response,
        ) == (branch.status, branch.accent)


def test_answered_axis_inherits_the_top_level_next() -> None:
    envelope = _envelope({"next": {"prompt": "continue after review"}})

    policy = resolve_gate_followup(
        envelope, gate_state="answered", response=_response("a")
    )

    assert policy is not None
    assert policy.branch_key == "a"
    assert policy.prompt == "continue after review"
    assert policy.output == ("results",)
    assert policy.fork == "session"


def test_branch_next_overrides_the_top_level_next() -> None:
    envelope = _envelope(
        {
            "next": {"prompt": "top-level prompt"},
            "branches": {"a": {"prompt": "branch-specific prompt"}},
        }
    )

    policy = resolve_gate_followup(
        envelope, gate_state="answered", response=_response("a")
    )

    assert policy is not None
    assert policy.prompt == "branch-specific prompt"


def test_tale_approve_commit_branch_resolves_coder_followup() -> None:
    envelope = _tale_envelope()

    policy = resolve_gate_followup(
        envelope, gate_state="answered", response=_response("approve", "commit")
    )

    assert policy is not None
    assert policy.branch_key == "approve+commit"
    assert policy.prompt == "Implement the approved plan."
    assert policy.fork == "none"
    assert policy.suffix == PLAN_CHAIN_CODER_SUFFIX
    assert policy.role == "code"
    assert policy.raw_prompt is True
    assert resolve_gate_branch_presentation(
        envelope, gate_state="answered", response=_response("approve", "commit")
    ) == ("TALE APPROVED", "#00D7D7")


def test_tale_approve_only_branch_resolves_coder_followup() -> None:
    envelope = _tale_envelope()

    policy = resolve_gate_followup(
        envelope, gate_state="answered", response=_response("approve")
    )

    assert policy is not None
    assert policy.branch_key == "approve"
    assert policy.prompt == "Implement the approved plan."
    assert policy.fork == "none"
    assert policy.suffix == PLAN_CHAIN_CODER_SUFFIX
    assert policy.role == "code"
    assert policy.raw_prompt is True
    assert resolve_gate_branch_presentation(
        envelope, gate_state="answered", response=_response("approve")
    ) == ("PLAN APPROVED", "#00D7AF")


@pytest.mark.parametrize(
    ("kind", "tier", "branches"),
    [
        ("plan", "tale", (("approve", "commit"), ("reject",), ("feedback",))),
        ("epic_plan", "epic", (("approve",), ("reject",), ("feedback",))),
    ],
)
def test_plan_gate_turn_creation_and_settlement_branch_policy_stay_in_sync(
    kind: str,
    tier: PlanGateTier,
    branches: tuple[tuple[str, ...], ...],
) -> None:
    shell = plan_gate_turn_block(tier)
    creation_parsed = GateTurnSpec.from_mapping(
        shell,
        branches=branches,
        allow_branch_subsets=subset_branches_allowed(kind),
    )

    _assert_settlement_accepts_created_shell_branches(
        kind=kind,
        turn=shell,
        branches=branches,
        creation_parsed=creation_parsed,
    )


def test_question_gate_turn_creation_and_settlement_branch_policy_stay_in_sync() -> (
    None
):
    request = _question_gate_turn_request()
    branches = (("submit",),)
    creation_parsed = GateTurnSpec.from_mapping(
        request["turn"],
        branches=branches,
        allow_branch_subsets=subset_branches_allowed(request["kind"]),
    )

    _assert_settlement_accepts_created_shell_branches(
        kind=str(request["kind"]),
        turn=request["turn"],
        branches=branches,
        creation_parsed=creation_parsed,
    )


def test_explicit_null_prompt_on_branch_suppresses_followup() -> None:
    envelope = _envelope(
        {
            "next": {"prompt": "top-level prompt"},
            "branches": {"a": {"prompt": None}},
        }
    )

    policy = resolve_gate_followup(
        envelope, gate_state="answered", response=_response("a")
    )

    assert policy is None


def test_explicit_null_prompt_at_top_level_suppresses_followup() -> None:
    envelope = _envelope({"next": {"prompt": None}})

    policy = resolve_gate_followup(
        envelope, gate_state="answered", response=_response("a")
    )

    assert policy is None


def test_absent_timeout_key_resolves_to_no_followup() -> None:
    envelope = _envelope({"next": {"prompt": "top-level prompt"}})

    policy = resolve_gate_followup(envelope, gate_state="timeout", response={})

    assert policy is None


def test_present_timeout_key_resolves() -> None:
    envelope = _envelope({"branches": {"timeout": {"prompt": "handle the timeout"}}})

    policy = resolve_gate_followup(envelope, gate_state="timeout", response={})

    assert policy is not None
    assert policy.branch_key == "timeout"
    assert policy.prompt == "handle the timeout"


def test_present_stopped_key_resolves() -> None:
    envelope = _envelope({"branches": {"stopped": {"prompt": "handle the stop"}}})

    policy = resolve_gate_followup(envelope, gate_state="stopped", response={})

    assert policy is not None
    assert policy.branch_key == "stopped"
    assert policy.prompt == "handle the stop"


def test_present_failed_key_resolves() -> None:
    envelope = _envelope({"branches": {"failed": {"prompt": "handle the failure"}}})

    policy = resolve_gate_followup(envelope, gate_state="failed", response={})

    assert policy is not None
    assert policy.branch_key == "failed"
    assert policy.prompt == "handle the failure"


def test_lost_resolves_against_the_failed_branch() -> None:
    envelope = _envelope({"branches": {"failed": {"prompt": "handle the failure"}}})

    policy = resolve_gate_followup(envelope, gate_state="lost", response={})

    assert policy is not None
    assert policy.branch_key == "failed"
    assert policy.prompt == "handle the failure"


def test_absent_lost_branch_resolves_to_no_followup() -> None:
    envelope = _envelope({"next": {"prompt": "top-level prompt"}})

    policy = resolve_gate_followup(envelope, gate_state="lost", response={})

    assert policy is None


def test_and_branch_key_joins_selected_ids_in_query_order() -> None:
    envelope = _envelope(
        {"branches": {"a+b": {"prompt": "and-branch prompt"}}},
        branches=[["a", "b"]],
    )

    policy = resolve_gate_followup(
        envelope, gate_state="answered", response=_response("a", "b")
    )

    assert policy is not None
    assert policy.branch_key == "a+b"
    assert policy.prompt == "and-branch prompt"


def test_malformed_shell_block_resolves_to_no_followup_without_raising() -> None:
    envelope: dict[str, Any] = {"shell": "not-an-object", "branches": [["a"]]}

    assert resolve_gate_followup(envelope, gate_state="answered", response={}) is None
    assert resolve_gate_branch_presentation(
        envelope, gate_state="answered", response={}
    ) == (None, None)


def test_missing_shell_block_resolves_to_no_followup() -> None:
    envelope: dict[str, Any] = {"branches": [["a"]]}

    assert resolve_gate_followup(envelope, gate_state="answered", response={}) is None


def test_settlement_branch_key_for_each_axis() -> None:
    assert (
        settlement_branch_key({}, gate_state="answered", response=_response("a")) == "a"
    )
    assert (
        settlement_branch_key({}, gate_state="completed", response=_response("a"))
        == "a"
    )
    assert settlement_branch_key({}, gate_state="timeout", response={}) == "timeout"
    assert settlement_branch_key({}, gate_state="stopped", response={}) == "stopped"
    assert settlement_branch_key({}, gate_state="failed", response={}) == "failed"
    assert settlement_branch_key({}, gate_state="lost", response={}) == "failed"


def test_branch_presentation_override_is_independent_of_followup() -> None:
    envelope = _envelope(
        {"branches": {"a": {"status": "APPROVED", "accent": "#00D7AF"}}}
    )

    status, accent = resolve_gate_branch_presentation(
        envelope, gate_state="answered", response=_response("a")
    )

    assert status == "APPROVED"
    assert accent == "#00D7AF"
    # No prompt declared on the branch or top level, so no follow-up.
    assert (
        resolve_gate_followup(envelope, gate_state="answered", response=_response("a"))
        is None
    )


def test_unmapped_branch_presentation_is_none() -> None:
    envelope = _envelope({"next": {"prompt": "top-level prompt"}})

    assert resolve_gate_branch_presentation(
        envelope, gate_state="answered", response=_response("a")
    ) == (None, None)
