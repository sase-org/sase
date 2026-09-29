"""Read-only resolver for gateless ``sase plan approve`` runs.

Facade preserving the original public import path. Implementation lives in
:mod:`sase.main.plan_direct_approval_types`,
:mod:`sase.main.plan_direct_approval_prompt`, and
:mod:`sase.main.plan_direct_approval_resolve`.
"""

from __future__ import annotations

from sase.main.plan_direct_approval_prompt import compose_coder_prompt
from sase.main.plan_direct_approval_resolve import (
    already_implemented_refusal,
    coder_running_refusal,
    resolve_direct_approval,
)
from sase.main.plan_direct_approval_types import (
    CoderPlacement,
    DirectApprovalKind,
    DirectApprovalLocation,
    DirectApprovalPlan,
    DirectApprovalRefusal,
    DirectApprovalRefused,
    DirectApprovalRequest,
    PlacementMode,
    RetiredGate,
    RetiredGateState,
)

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
    "already_implemented_refusal",
    "coder_running_refusal",
    "compose_coder_prompt",
    "resolve_direct_approval",
]
