"""Classifier for distinguishing axe-spawned vs manual agents."""

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .agent import Agent


def agent_source(agent: "Agent") -> Literal["axe", "manual"]:
    """Classify *agent* as ``"axe"`` (workflow-spawned) or ``"manual"``.

    An agent is ``axe`` when it carries any axe lineage marker — either it
    sits inside a workflow (``workflow is not None``) or it is itself a
    workflow step (``step_type is not None``). Everything else is
    classified as ``manual``.

    Edge case: a manually-launched root-of-workflow agent is classified as
    ``manual`` until a workflow attaches to it. That's the intended
    behavior — at the moment of evaluation it is still a manual run.
    """
    if agent.workflow is not None or agent.step_type is not None:
        return "axe"
    return "manual"
