"""Built-in standard plan-chain family definition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

from sase.plan_approval_choices import (
    PLAN_APPROVAL_CHOICE_IDS,
    approval_protocol_for_choice,
)
from sase.plan_chain import (
    AGENT_FAMILY_SEPARATOR,
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
)

STANDARD_PLAN_CHAIN_ID = "standard_plan_chain"
STANDARD_PLAN_CHAIN_VERSION = 1

type HandoffEventKind = Literal[
    "plan_submitted",
    "questions_submitted",
    "role_completed",
]
type GateRendererId = Literal["plan_approval", "user_question"]
type RoleCompletedOutcome = Literal["success", "failed", "stopped"]


@dataclass(frozen=True)
class _FamilyRoleDefinition:
    """A role in the built-in standard plan-chain family."""

    id: str
    suffix: str | None = None
    label: str | None = None
    done_label: str | None = None
    prompt_template: str | None = None
    terminal: bool = False


@dataclass(frozen=True)
class _FamilyGateChoiceDefinition:
    """A plan-review choice as seen by the standard-chain evaluator."""

    id: str
    compatibility_response: dict[str, object] | None
    goto_role: str | None = None
    side_effect_ids: tuple[str, ...] = ()
    terminal: str | None = None


@dataclass(frozen=True)
class _FamilyGateDefinition:
    """A compatibility gate backed by an existing renderer/protocol."""

    id: str
    renderer: GateRendererId
    choices: tuple[_FamilyGateChoiceDefinition, ...] = ()
    return_to_interrupted_role: bool = False


@dataclass(frozen=True)
class _FamilyEventDefinition:
    """An event-to-gate mapping in the built-in family definition."""

    id: HandoffEventKind
    gate_id: str | None = None
    renderer: GateRendererId | None = None
    terminal: bool = False
    composition_rule: str | None = None


@dataclass(frozen=True)
class _FamilyDefinition:
    """Compiled, pure-Python definition for the built-in plan chain."""

    id: str
    version: int
    entry_role: str
    roles: tuple[_FamilyRoleDefinition, ...]
    gates: tuple[_FamilyGateDefinition, ...]
    events: tuple[_FamilyEventDefinition, ...]


def _choice_protocol(choice: str) -> dict[str, object] | None:
    try:
        protocol = approval_protocol_for_choice(choice)
    except KeyError:
        return None
    return {
        "action": protocol.action,
        "commit_plan": protocol.commit_plan,
        "run_coder": protocol.run_coder,
    }


def _choice_target_role(choice: str) -> str | None:
    if choice in {"approve", "run", "tale"}:
        return "code"
    if choice == "commit":
        return "commit"
    if choice == "feedback":
        return "feedback"
    return None


def _choice_side_effects(choice: str) -> tuple[str, ...]:
    if choice == "tale":
        return ("write_sdd", "commit_sdd", "set_sase_plan_env")
    if choice == "commit":
        return ("write_sdd", "commit_sdd")
    if choice == "epic":
        return (
            "write_sdd",
            "commit_sdd",
            "create_epic_beads",
            "launch_epic_work",
        )
    if choice in {"approve", "run"}:
        return ("write_sdd", "set_sase_plan_env")
    if choice == "feedback":
        return ("record_feedback", "replan")
    return ()


def standard_plan_chain_definition() -> _FamilyDefinition:
    """Return the compiled built-in family definition."""

    plan_choices = tuple(
        _FamilyGateChoiceDefinition(
            id=choice,
            compatibility_response=_choice_protocol(choice),
            goto_role=_choice_target_role(choice),
            side_effect_ids=_choice_side_effects(choice),
            terminal=(
                "plan_rejected"
                if choice == "reject"
                else "completed"
                if choice == "epic"
                else None
            ),
        )
        for choice in PLAN_APPROVAL_CHOICE_IDS
    )
    return _FamilyDefinition(
        id=STANDARD_PLAN_CHAIN_ID,
        version=STANDARD_PLAN_CHAIN_VERSION,
        entry_role="root",
        roles=(
            _FamilyRoleDefinition(id="root"),
            _FamilyRoleDefinition(
                id="plan",
                suffix=PLAN_CHAIN_PLAN_SUFFIX,
                prompt_template="initial_prompt",
            ),
            _FamilyRoleDefinition(
                id="q",
                suffix=f"{AGENT_FAMILY_SEPARATOR}@",
                prompt_template="standard_question_followup_prompt",
            ),
            _FamilyRoleDefinition(
                id="feedback",
                suffix=f"{PLAN_CHAIN_PLAN_SUFFIX}-@",
                prompt_template="standard_feedback_replan_prompt",
            ),
            _FamilyRoleDefinition(
                id="code",
                suffix=PLAN_CHAIN_CODER_SUFFIX,
                prompt_template="standard_coder_prompt",
            ),
            _FamilyRoleDefinition(
                id="commit",
                suffix=PLAN_CHAIN_COMMIT_SUFFIX,
                terminal=True,
            ),
        ),
        gates=(
            _FamilyGateDefinition(
                id="plan_review",
                renderer="plan_approval",
                choices=plan_choices,
            ),
            _FamilyGateDefinition(
                id="user_questions",
                renderer="user_question",
                return_to_interrupted_role=True,
            ),
        ),
        events=(
            _FamilyEventDefinition(
                id="plan_submitted",
                gate_id="plan_review",
                renderer="plan_approval",
            ),
            _FamilyEventDefinition(
                id="questions_submitted",
                gate_id="user_questions",
                renderer="user_question",
            ),
            _FamilyEventDefinition(
                id="role_completed",
                terminal=True,
                composition_rule=(
                    "after_followup_workflow_including_embedded_vcs_refs"
                ),
            ),
        ),
    )


def standard_plan_chain_event_definition(
    kind: HandoffEventKind,
) -> _FamilyEventDefinition:
    """Return the built-in event definition for a lifecycle event kind."""

    for event in standard_plan_chain_definition().events:
        if event.id == kind:
            return event
    raise KeyError(kind)


def _definition_hash() -> str:
    payload = json.dumps(
        asdict(standard_plan_chain_definition()),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


STANDARD_PLAN_CHAIN_CONFIG_HASH = _definition_hash()
