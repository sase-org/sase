"""Custom agent workflow mixin for the ace TUI app."""

from ._agent_launch import AgentLaunchMixin
from ._editor import EditorMixin
from ._entry_points import EntryPointsMixin
from ._prompt_bar import PromptBarMixin
from ._ref_resolution import RefResolutionMixin
from ._workflow_exec import WorkflowExecMixin


class AgentWorkflowMixin(
    EntryPointsMixin,
    PromptBarMixin,
    EditorMixin,
    AgentLaunchMixin,
    WorkflowExecMixin,
    RefResolutionMixin,
):
    """Mixin providing custom agent workflow actions."""

    pass
