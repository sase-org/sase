"""Shared display typing for workflow steps."""

from __future__ import annotations

from sase.xprompt.workflow_models import WorkflowStep


def workflow_step_type_label(step: WorkflowStep) -> tuple[str, str]:
    """Return the stable display type and compact label for *step*."""
    if step.agent:
        return "agent", step.agent.split("\n", 1)[0][:50]
    if step.bash:
        return "bash", step.bash
    if step.python:
        return "python", step.python
    if step.prompt_part:
        return "prompt_part", step.prompt_part.split("\n", 1)[0][:50]
    return "unknown", "?"


__all__ = ["workflow_step_type_label"]
