"""Runtime dataclasses for the built-in standard plan chain."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.agent_family.custom_definitions import AgentFamilyRoleDefinition
from sase.agent_family.standard_plan_chain_definition import (
    STANDARD_PLAN_CHAIN_CONFIG_HASH,
    STANDARD_PLAN_CHAIN_ID,
    STANDARD_PLAN_CHAIN_VERSION,
    GateRendererId,
    HandoffEventKind,
)


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
    """Typed lifecycle event consumed by the standard-chain evaluator.

    ``role_completed`` is emitted after the follow-up workflow returns, so a
    later post-code role naturally sequences after reconstructed embedded VCS
    refs such as ``#propose`` and ``#commit``.
    """

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
    config_id: str = STANDARD_PLAN_CHAIN_ID
    config_version: int = STANDARD_PLAN_CHAIN_VERSION
    config_hash: str = STANDARD_PLAN_CHAIN_CONFIG_HASH
    custom_role: AgentFamilyRoleDefinition | None = None

    def as_meta_fields(self) -> dict[str, object]:
        fields: dict[str, object] = {
            "agent_family_config_id": self.config_id,
            "agent_family_config_version": self.config_version,
            "agent_family_config_hash": self.config_hash,
            "active_gate_id": self.active_gate_id,
            "active_gate_renderer": self.active_gate_renderer,
            "family_state": self.family_state.as_json(),
        }
        if self.custom_role is not None:
            fields["agent_family_custom_role"] = self.custom_role.as_snapshot()
        return fields

    def as_followup_relationships(self) -> dict[str, object]:
        fields = self.as_meta_fields()
        return {
            key: value
            for key, value in fields.items()
            if key not in {"active_gate_id", "active_gate_renderer"}
        }


@dataclass(frozen=True)
class CustomRoleTransition:
    """A custom role the evaluator selected as the next family member."""

    role: AgentFamilyRoleDefinition
    runtime_metadata: FamilyRuntimeMetadata
    cap_exhausted: bool = False
    failure_policy: str | None = None


@dataclass(frozen=True)
class FamilyEvaluation:
    """Result of routing a lifecycle event through the standard chain."""

    event: HandoffEvent
    gate_id: str | None
    renderer: GateRendererId | None
    runtime_metadata: FamilyRuntimeMetadata
    terminal: bool = False
    composition_rule: str | None = None
    custom_role: CustomRoleTransition | None = None
    terminal_reason: str | None = None


@dataclass(frozen=True)
class PlanApprovalTransition:
    """Pure transition selected after a plan-review response."""

    target_role: str | None
    role_suffix: str | None
    suffix_template: str | None
    terminal_outcome: str | None
    side_effect_ids: tuple[str, ...]
    runtime_metadata: FamilyRuntimeMetadata
    custom_role: CustomRoleTransition | None = None


@dataclass(frozen=True)
class QuestionsTransition:
    """Pure transition selected after a user-question response."""

    followup_role: str
    suffix_template: str
    runtime_metadata: FamilyRuntimeMetadata
