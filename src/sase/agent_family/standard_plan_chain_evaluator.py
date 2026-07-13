"""Pure evaluator for the built-in standard plan chain."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.agent_family.custom_definitions import (
    AgentFamilyRoleDefinition,
    role_definition_from_snapshot,
)
from sase.agent_family.standard_plan_chain_definition import (
    HandoffEventKind,
    standard_plan_chain_event_definition,
)
from sase.agent_family.standard_plan_chain_models import (
    CustomRoleTransition,
    FamilyEvaluation,
    FamilyRuntimeMetadata,
    FamilyStateSnapshot,
    HandoffEvent,
    PlanApprovalTransition,
    QuestionsTransition,
)
from sase.plan_chain import (
    AGENT_FAMILY_SEPARATOR,
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_role_for_suffix,
    is_root_question_suffix,
    question_followup_suffix_template,
)


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
    visit_counts: Mapping[str, int] | None = None,
) -> FamilyStateSnapshot:
    """Build a compact standard-chain state snapshot."""

    current_role = _role_for_suffix(
        current_role_suffix,
        agent_family_role=agent_family_role,
    )
    next_visit_counts: dict[str, int] = dict(visit_counts or {})
    if current_role:
        next_visit_counts.setdefault(current_role, 1)
    return FamilyStateSnapshot(
        current_role=current_role,
        current_role_suffix=current_role_suffix,
        feedback_count=len(feedback_bullets),
        qa_round_count=qa_round_count,
        saved_chat_suffixes=tuple(suffix for suffix in saved_chat_suffixes if suffix),
        visit_counts=next_visit_counts,
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


def _custom_runtime_metadata(
    role: AgentFamilyRoleDefinition,
    family_state: FamilyStateSnapshot,
) -> FamilyRuntimeMetadata:
    return FamilyRuntimeMetadata(
        active_gate_id=None,
        active_gate_renderer=None,
        family_state=family_state,
        config_id=role.config_id,
        config_version=role.config_version,
        config_hash=role.config_hash,
        custom_role=role,
    )


def _select_custom_role_after(
    after_role: str,
    family_state: FamilyStateSnapshot,
    *,
    custom_roles: Sequence[AgentFamilyRoleDefinition],
    auto_mode: bool = False,
    outcome: object = "success",
) -> CustomRoleTransition | None:
    for role in custom_roles:
        if role.placement_after != after_role:
            continue
        if auto_mode and role.auto != "run":
            continue
        if outcome != "success":
            return CustomRoleTransition(
                role=role,
                runtime_metadata=_custom_runtime_metadata(role, family_state),
                failure_policy=role.on_failure,
            )
        prior_visits = int(family_state.visit_counts.get(role.id, 0) or 0)
        if prior_visits >= role.max_visits:
            return CustomRoleTransition(
                role=role,
                runtime_metadata=_custom_runtime_metadata(role, family_state),
                cap_exhausted=True,
            )
        visit_counts = dict(family_state.visit_counts)
        visit_counts[role.id] = prior_visits + 1
        next_state = FamilyStateSnapshot(
            current_role=role.id,
            current_role_suffix=role.suffix,
            feedback_count=family_state.feedback_count,
            qa_round_count=family_state.qa_round_count,
            saved_chat_suffixes=family_state.saved_chat_suffixes,
            visit_counts=visit_counts,
        )
        return CustomRoleTransition(
            role=role,
            runtime_metadata=_custom_runtime_metadata(role, next_state),
        )
    return None


def _custom_role_for_handoff_event(
    event: HandoffEvent,
    family_state: FamilyStateSnapshot,
    *,
    custom_roles: Sequence[AgentFamilyRoleDefinition],
    custom_role_snapshot: Mapping[str, object] | None,
) -> CustomRoleTransition | None:
    if event.kind != "role_completed":
        return None
    snapshotted_role = (
        role_definition_from_snapshot(custom_role_snapshot)
        if custom_role_snapshot is not None
        else None
    )
    if snapshotted_role is not None and event.interrupted_role == snapshotted_role.id:
        return None
    return _select_custom_role_after(
        event.interrupted_role,
        family_state,
        custom_roles=custom_roles,
        outcome=event.payload.get("outcome"),
    )


def evaluate_handoff_event(
    event: HandoffEvent,
    family_state: FamilyStateSnapshot,
    *,
    custom_roles: Sequence[AgentFamilyRoleDefinition] = (),
    custom_role_snapshot: Mapping[str, object] | None = None,
) -> FamilyEvaluation:
    """Route a typed lifecycle event through the built-in standard chain."""

    event_def = standard_plan_chain_event_definition(event.kind)
    custom_role = _custom_role_for_handoff_event(
        event,
        family_state,
        custom_roles=custom_roles,
        custom_role_snapshot=custom_role_snapshot,
    )
    terminal = event_def.terminal
    terminal_reason = None
    if custom_role is not None:
        terminal = custom_role.cap_exhausted or custom_role.failure_policy is not None
        terminal_reason = (
            "custom_role_cap_exhausted"
            if custom_role.cap_exhausted
            else custom_role.failure_policy
        )
    return FamilyEvaluation(
        event=event,
        gate_id=event_def.gate_id,
        renderer=event_def.renderer,
        runtime_metadata=FamilyRuntimeMetadata(
            active_gate_id=event_def.gate_id,
            active_gate_renderer=event_def.renderer,
            family_state=family_state,
        ),
        terminal=terminal,
        composition_rule=event_def.composition_rule,
        custom_role=custom_role,
        terminal_reason=terminal_reason,
    )


def family_runtime_metadata_for_role(
    role: str,
    *,
    role_suffix: str,
    feedback_count: int,
    qa_round_count: int,
    saved_chat_suffixes: Sequence[str] = (),
    visit_counts: Mapping[str, int] | None = None,
) -> FamilyRuntimeMetadata:
    """Return non-gated runtime metadata for a role that is about to run."""

    next_visit_counts = dict(visit_counts or {})
    if role:
        next_visit_counts.setdefault(role, 1)
    snapshot = FamilyStateSnapshot(
        current_role=role,
        current_role_suffix=role_suffix,
        feedback_count=feedback_count,
        qa_round_count=qa_round_count,
        saved_chat_suffixes=tuple(suffix for suffix in saved_chat_suffixes if suffix),
        visit_counts=next_visit_counts,
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
    if action == "epic":
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
    visit_counts: Mapping[str, int] | None = None,
    custom_roles: Sequence[AgentFamilyRoleDefinition] = (),
    auto_mode: bool = False,
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
        visit_counts=visit_counts,
    )
    custom_role = None
    if role == "code" and terminal is None:
        custom_role = _select_custom_role_after(
            "plan",
            FamilyStateSnapshot(
                current_role=role,
                current_role_suffix=role_suffix or suffix_template or "",
                feedback_count=feedback_count,
                qa_round_count=qa_round_count,
                saved_chat_suffixes=tuple(
                    suffix for suffix in saved_chat_suffixes if suffix
                ),
                visit_counts=dict(visit_counts or {}),
            ),
            custom_roles=custom_roles,
            auto_mode=auto_mode,
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
        custom_role=custom_role,
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
    from sase.agent.names import render_agent_name_template

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
            render_agent_name_template(suffix_template, "0"),
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
