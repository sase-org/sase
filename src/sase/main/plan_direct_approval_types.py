"""Public data model for gateless ``sase plan approve`` runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.main.plan_direct_approval_recovery import CoderRecovery, PriorCoder
    from sase.main.plan_pending_diagnosis import PlanGateHistory

DirectApprovalKind = Literal["tale", "commit", "approve", "epic"]
DirectApprovalLocation = Literal["scratch", "proposal", "committed"]
PlacementMode = Literal["session", "standalone"]
RetiredGateState = Literal["orphaned", "expired"]


@dataclass(frozen=True)
class DirectApprovalRequest:
    selector: str
    kind: DirectApprovalKind | None = None
    kind_explicit: bool = False
    coder_model: str | None = None
    coder_prompt: str | None = None
    wait: object = None
    project: str | None = None
    cwd: Path | None = None
    decide: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoderPlacement:
    mode: PlacementMode
    parent: str | None = None
    member_name: str | None = None
    agent_session: str | None = None
    reason: str | None = None
    planner_artifacts_dir: str | None = None
    suffix: str = "code"


@dataclass(frozen=True)
class RetiredGate:
    notification_id: str
    state: RetiredGateState
    bundle_path: Path | None = None
    action_data: dict[str, str] | None = None


@dataclass(frozen=True)
class DirectApprovalPlan:
    request: DirectApprovalRequest
    kind: DirectApprovalKind
    source_path: Path
    location: DirectApprovalLocation
    name: str
    title: str | None
    size: str | None
    project: str
    project_tag: str
    planner: str | None
    gate: RetiredGate | None
    placement: CoderPlacement
    model_directive: str
    bead: str | None = None
    predicted_plan_ref: str = ""
    coder_prompt_preview: str = ""
    recovery: CoderRecovery | None = None
    decide_values: dict[str, Any] = field(default_factory=dict)
    decide_rows: tuple[dict[str, Any], ...] = ()
    decide_sheet: dict[str, Any] | None = None


@dataclass(frozen=True)
class DirectApprovalRefusal:
    code: str
    header: str
    detail_lines: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()


class DirectApprovalRefused(Exception):
    def __init__(self, refusal: DirectApprovalRefusal) -> None:
        super().__init__(refusal.header)
        self.refusal = refusal


__all__ = [
    "CoderPlacement",
    "DirectApprovalKind",
    "DirectApprovalLocation",
    "DirectApprovalPlan",
    "DirectApprovalRefusal",
    "DirectApprovalRefused",
    "DirectApprovalRequest",
    "PlacementMode",
    "RetiredGate",
    "RetiredGateState",
]
