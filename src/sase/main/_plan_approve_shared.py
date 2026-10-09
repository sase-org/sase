"""Shared helpers needed by more than one plan-approve module.

Public names only: sibling ``plan_approve_*`` modules import these
without touching a ``_``-prefixed symbol.
"""

from __future__ import annotations

from sase.plan_approval_actions import PlanApprovalActionError


class RenderedSelectionError(PlanApprovalActionError):
    """A selection error already rendered by the shared renderer."""

    _sase_rendered = True


def rendered_error(code: str, target: str, message: str) -> PlanApprovalActionError:
    """Build a selection error already rendered by the shared renderer."""
    return RenderedSelectionError(code, target, message)


__all__ = ["RenderedSelectionError", "rendered_error"]
