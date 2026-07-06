"""Built-in standard plan-chain family definition and pure evaluator."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sase.plan_approval_choices import (
    PLAN_APPROVAL_CHOICE_IDS,
    approval_protocol_for_choice,
)
from sase.plan_chain import (
    AGENT_FAMILY_SEPARATOR,
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_LEGEND_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_role_for_suffix,
    is_root_question_suffix,
    question_followup_suffix_template,
)

STANDARD_PLAN_CHAIN_ID = "standard_plan_chain"
STANDARD_PLAN_CHAIN_VERSION = 1

type HandoffEventKind = Literal["plan_submitted", "questions_submitted"]
type GateRendererId = Literal["plan_approval", "user_question"]


@dataclass(frozen=True)
class _FamilyRoleDefinition:
    """A role in the built-in standard plan-chain family."""

    id: str
    suffix: str | None = None
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
    gate_id: str
    renderer: GateRendererId


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
    if choice == "epic":
        return "epic"
    if choice == "legend":
        return "legend"
    if choice == "feedback":
        return "feedback"
    return None


def _choice_side_effects(choice: str) -> tuple[str, ...]:
    if choice == "tale":
        return ("write_sdd", "commit_sdd", "set_sase_plan_env")
    if choice == "commit":
        return ("write_sdd", "commit_sdd")
    if choice in {"epic", "legend"}:
        return ("write_sdd", "commit_sdd", f"launch_{choice}_creator")
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
            terminal="plan_rejected" if choice == "reject" else None,
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
                id="epic",
                suffix=PLAN_CHAIN_EPIC_SUFFIX,
                prompt_template="bd/new_epic",
            ),
            _FamilyRoleDefinition(
                id="legend",
                suffix=PLAN_CHAIN_LEGEND_SUFFIX,
                prompt_template="bd/new_legend",
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
        ),
    )


def _definition_hash() -> str:
    payload = json.dumps(
        asdict(standard_plan_chain_definition()),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


STANDARD_PLAN_CHAIN_CONFIG_HASH = _definition_hash()


@dataclass(frozen=True)
class FamilyStateSnapshot:
    """Compact runtime state used by the pure evaluator."""

    current_role: str
    current_role_suffix: str
    feedback_count: int = 0
    qa_round_count: int = 0
    saved_chat_suffixes: tuple[str, ...] = ()
    visit_counts: Mapping[str, int] = field(default_factory=dict)

    def as_json(self) -> dict[str, object]:
        return {
            "current_role": self.current_role,
            "current_role_suffix": self.current_role_suffix,
            "feedback_count": self.feedback_count,
            "qa_round_count": self.qa_round_count,
            "saved_chat_suffixes": list(self.saved_chat_suffixes),
            "visit_counts": dict(self.visit_counts),
        }


@dataclass(frozen=True)
class HandoffEvent:
    """Typed marker event consumed by the standard-chain evaluator."""

    kind: HandoffEventKind
    interrupted_role: str
    artifacts_dir: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class FamilyRuntimeMetadata:
    """Metadata persisted on artifacts for family-definition identity/state."""

    active_gate_id: str | None
    active_gate_renderer: GateRendererId | None
    family_state: FamilyStateSnapshot

    def as_meta_fields(self) -> dict[str, object]:
        return {
            "agent_family_config_id": STANDARD_PLAN_CHAIN_ID,
            "agent_family_config_version": STANDARD_PLAN_CHAIN_VERSION,
            "agent_family_config_hash": STANDARD_PLAN_CHAIN_CONFIG_HASH,
            "active_gate_id": self.active_gate_id,
            "active_gate_renderer": self.active_gate_renderer,
            "family_state": self.family_state.as_json(),
        }

    def as_followup_relationships(self) -> dict[str, object]:
        fields = self.as_meta_fields()
        return {
            key: value
            for key, value in fields.items()
            if key not in {"active_gate_id", "active_gate_renderer"}
        }


@dataclass(frozen=True)
class FamilyEvaluation:
    """Result of routing a handoff event to a compatibility gate."""

    event: HandoffEvent
    gate_id: str
    renderer: GateRendererId
    runtime_metadata: FamilyRuntimeMetadata


@dataclass(frozen=True)
class PlanApprovalTransition:
    """Pure transition selected after a plan-review response."""

    target_role: str | None
    role_suffix: str | None
    suffix_template: str | None
    terminal_outcome: str | None
    side_effect_ids: tuple[str, ...]
    runtime_metadata: FamilyRuntimeMetadata


@dataclass(frozen=True)
class QuestionsTransition:
    """Pure transition selected after a user-question response."""

    followup_role: str
    suffix_template: str
    runtime_metadata: FamilyRuntimeMetadata


def _role_for_suffix(role_suffix: str, *, agent_family_role: object = None) -> str:
    if not role_suffix:
        return "root"
    return (
        agent_family_role_for_suffix(
            role_suffix,
            agent_family_role=agent_family_role,
        )
        or "root"
    )


def family_state_snapshot(
    *,
    current_role_suffix: str,
    feedback_bullets: Sequence[str] = (),
    qa_round_count: int = 0,
    saved_chat_suffixes: Sequence[str] = (),
    agent_family_role: object = None,
) -> FamilyStateSnapshot:
    """Build a compact standard-chain state snapshot."""

    current_role = _role_for_suffix(
        current_role_suffix,
        agent_family_role=agent_family_role,
    )
    visit_counts: dict[str, int] = {}
    if current_role:
        visit_counts[current_role] = 1
    return FamilyStateSnapshot(
        current_role=current_role,
        current_role_suffix=current_role_suffix,
        feedback_count=len(feedback_bullets),
        qa_round_count=qa_round_count,
        saved_chat_suffixes=tuple(suffix for suffix in saved_chat_suffixes if suffix),
        visit_counts=visit_counts,
    )


def build_handoff_event(
    *,
    kind: HandoffEventKind,
    artifacts_dir: str,
    payload: Mapping[str, Any],
    current_role_suffix: str,
    agent_family_role: object = None,
) -> HandoffEvent:
    """Normalize a legacy marker payload into a typed standard-chain event."""

    return HandoffEvent(
        kind=kind,
        interrupted_role=_role_for_suffix(
            current_role_suffix,
            agent_family_role=agent_family_role,
        ),
        artifacts_dir=artifacts_dir,
        payload=dict(payload),
    )


def _event_definition(kind: HandoffEventKind) -> _FamilyEventDefinition:
    for event in standard_plan_chain_definition().events:
        if event.id == kind:
            return event
    raise KeyError(kind)


def evaluate_handoff_event(
    event: HandoffEvent,
    family_state: FamilyStateSnapshot,
) -> FamilyEvaluation:
    """Route a typed handoff event to the built-in compatibility gate."""

    event_def = _event_definition(event.kind)
    return FamilyEvaluation(
        event=event,
        gate_id=event_def.gate_id,
        renderer=event_def.renderer,
        runtime_metadata=FamilyRuntimeMetadata(
            active_gate_id=event_def.gate_id,
            active_gate_renderer=event_def.renderer,
            family_state=family_state,
        ),
    )


def family_runtime_metadata_for_role(
    role: str,
    *,
    role_suffix: str,
    feedback_count: int,
    qa_round_count: int,
    saved_chat_suffixes: Sequence[str] = (),
) -> FamilyRuntimeMetadata:
    """Return non-gated runtime metadata for a role that is about to run."""

    snapshot = FamilyStateSnapshot(
        current_role=role,
        current_role_suffix=role_suffix,
        feedback_count=feedback_count,
        qa_round_count=qa_round_count,
        saved_chat_suffixes=tuple(suffix for suffix in saved_chat_suffixes if suffix),
        visit_counts={role: 1} if role else {},
    )
    return FamilyRuntimeMetadata(
        active_gate_id=None,
        active_gate_renderer=None,
        family_state=snapshot,
    )


def _accepted_role_and_suffix(
    *,
    action: str,
    run_coder: bool,
) -> tuple[str, str | None, str | None, str | None]:
    if action == "feedback":
        return "feedback", None, f"{PLAN_CHAIN_PLAN_SUFFIX}-@", None
    if action == "epic":
        return "epic", PLAN_CHAIN_EPIC_SUFFIX, None, None
    if action == "legend":
        return "legend", PLAN_CHAIN_LEGEND_SUFFIX, None, None
    if action == "approve" and not run_coder:
        return "commit", PLAN_CHAIN_COMMIT_SUFFIX, None, "plan_committed"
    return "code", PLAN_CHAIN_CODER_SUFFIX, None, None


def _transition_side_effect_ids(
    *,
    action: str,
    commit_plan: bool,
    run_coder: bool,
) -> tuple[str, ...]:
    if action == "feedback":
        return ("record_feedback", "replan")
    if action in {"epic", "legend"}:
        return ("write_sdd", "commit_sdd", f"launch_{action}_creator")
    effects = ["write_sdd"]
    if commit_plan:
        effects.append("commit_sdd")
    if run_coder:
        effects.append("set_sase_plan_env")
    return tuple(effects)


def evaluate_plan_approval_transition(
    *,
    action: str,
    commit_plan: bool,
    run_coder: bool,
    feedback_count: int,
    qa_round_count: int,
    saved_chat_suffixes: Sequence[str] = (),
) -> PlanApprovalTransition:
    """Evaluate the next standard-chain transition after plan review."""

    role, role_suffix, suffix_template, terminal = _accepted_role_and_suffix(
        action=action,
        run_coder=run_coder,
    )
    runtime = family_runtime_metadata_for_role(
        role,
        role_suffix=role_suffix or suffix_template or "",
        feedback_count=feedback_count,
        qa_round_count=qa_round_count,
        saved_chat_suffixes=saved_chat_suffixes,
    )
    return PlanApprovalTransition(
        target_role=role,
        role_suffix=role_suffix,
        suffix_template=suffix_template,
        terminal_outcome=terminal,
        side_effect_ids=_transition_side_effect_ids(
            action=action,
            commit_plan=commit_plan,
            run_coder=run_coder,
        ),
        runtime_metadata=runtime,
    )


def evaluate_questions_transition(
    *,
    interrupted_suffix: str,
    interrupted_role: str | None,
    feedback_count: int,
    qa_round_count: int,
    saved_chat_suffixes: Sequence[str] = (),
) -> QuestionsTransition:
    """Evaluate the follow-up role/suffix template after Q&A completes."""

    root_sequence = is_root_question_suffix(
        interrupted_suffix,
        agent_family_role=interrupted_role,
    )
    suffix_template = (
        f"{AGENT_FAMILY_SEPARATOR}@"
        if root_sequence
        else question_followup_suffix_template(
            interrupted_suffix,
            agent_family_role=interrupted_role,
        )
    )
    followup_role = (
        "q"
        if root_sequence
        else agent_family_role_for_suffix(
            suffix_template.replace("@", "0"),
            agent_family_role=interrupted_role,
        )
        or interrupted_role
        or "q"
    )
    runtime = family_runtime_metadata_for_role(
        followup_role,
        role_suffix=suffix_template,
        feedback_count=feedback_count,
        qa_round_count=qa_round_count,
        saved_chat_suffixes=saved_chat_suffixes,
    )
    return QuestionsTransition(
        followup_role=followup_role,
        suffix_template=suffix_template,
        runtime_metadata=runtime,
    )
