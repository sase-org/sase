"""Workflow execution and embedding for macro workflows.

Facade preserving the original ``sase.macro.workflow_runner`` import path.
Implementation lives in :mod:`sase.macro.workflow_runner_flatten` and
:mod:`sase.macro.workflow_runner_execute`; shared override keys live in
:mod:`sase.macro._workflow_runner_args`.
"""

from .workflow_runner_execute import (
    WorkflowResult,
    execute_workflow,
    expand_workflow_for_embedding,
)
from .workflow_runner_flatten import (
    invalid_explicit_standalone_message,
    is_workflow_reference,
    standalone_deprecation_message,
)

__all__ = [
    "WorkflowResult",
    "execute_workflow",
    "expand_workflow_for_embedding",
    "invalid_explicit_standalone_message",
    "is_workflow_reference",
    "standalone_deprecation_message",
]
