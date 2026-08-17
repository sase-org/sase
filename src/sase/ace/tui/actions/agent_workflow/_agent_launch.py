"""Agent launch mixin for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._launch_delta import LaunchDeltaMixin
from ._launch_procs import LaunchProcMixin
from ._launch_start import AgentLaunchStartMixin
from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.patch import Patch
    from sase.ace.tui.modals import SelectionItem
    from sase.ace.tui.models import Agent


class AgentLaunchMixin(
    AgentLaunchStartMixin,
    LaunchDeltaMixin,
    LaunchProcMixin,
):
    """Internal mixin providing agent launching functionality."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    marked_indices: set[int]
    _agents: list[Agent]

    # State for prompt input (from AgentWorkflowMixin)
    _prompt_context: PromptContext | None = None
    # State for repeat-last-+/Ctrl+Space selection (from EntryPointsMixin)
    _last_custom_agent_selection: SelectionItem | None = None
