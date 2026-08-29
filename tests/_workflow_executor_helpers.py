"""Shared helpers for WorkflowExecutor tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from sase.xprompt import HITLHandler, HITLResult
from sase.xprompt.models import OutputSpec
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _create_test_workflow(
    name: str = "test_workflow",
    steps: list[WorkflowStep] | None = None,
) -> Workflow:
    """Create a test workflow with the given steps."""
    if steps is None:
        steps = [
            WorkflowStep(
                name="step1",
                agent="Test prompt",
                output=OutputSpec(
                    type="json_schema",
                    schema={
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                        "required": ["result"],
                    },
                ),
                hitl=False,
            )
        ]
    return Workflow(
        name=name,
        steps=steps,
    )


def _create_mock_hitl_handler(action: str = "accept") -> HITLHandler:
    """Create a mock HITL handler that returns the specified action."""
    handler = MagicMock(spec=HITLHandler)
    handler.prompt.return_value = HITLResult(action=action)
    return handler
