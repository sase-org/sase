"""Shared routing for accepted tale follow-up agents."""

from __future__ import annotations

from pathlib import Path

from sase.plan_approval_actions import require_plan_approval_validation


class _TaleFollowupRoutingError(RuntimeError):
    """Tale validation succeeded without enough data to choose a follow-up model."""


def validated_tale_followup_model_directive(plan_file: str | Path) -> str:
    """Return the size-derived ``%model`` value for an approved tale plan.

    The approval gate and runtime handoff both consume tales in launch mode so
    legacy sizeless tales normalize to ``medium`` before routing. The actual
    size-to-alias mapping stays in :mod:`sase.bead.work`, where bead and task
    worker launches already source it.
    """
    validation = require_plan_approval_validation(Path(plan_file).expanduser(), "tale")
    plan = validation.plan
    if plan is None or not plan.size:
        raise _TaleFollowupRoutingError(
            f"{plan_file} passed tale validation but did not produce a launch size"
        )

    from sase.bead.work import phase_model_directive_value

    return phase_model_directive_value(None, size=plan.size)


__all__ = [
    "validated_tale_followup_model_directive",
]
