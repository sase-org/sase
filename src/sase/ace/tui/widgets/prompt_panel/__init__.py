"""Agent prompt panel widget for the ace TUI."""

from textual.widgets import Static

from ._agent_display import AgentDisplayMixin
from ._helpers import (
    aggregate_meta_fields,
    extract_meta_fields,
    format_embedded_workflows,
    format_meta_key,
    load_embedded_workflows,
)
from ._workflow_display import WorkflowDisplayMixin


class AgentPromptPanel(AgentDisplayMixin, WorkflowDisplayMixin, Static):
    """Top panel showing agent details and the input prompt."""


__all__ = [
    "AgentPromptPanel",
    "aggregate_meta_fields",
    "extract_meta_fields",
    "format_embedded_workflows",
    "format_meta_key",
    "load_embedded_workflows",
]
