"""Prompt input bar management and event handlers for agent workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._prompt_bar_memory_panel import PromptBarMemoryPanelMixin
from ._prompt_bar_mini_xprompt_pane import PromptBarMiniXPromptPaneMixin
from ._prompt_bar_snippets_panel import PromptBarSnippetsPanelMixin
from ._prompt_bar_mount import PromptBarMountMixin
from ._prompt_bar_requests import PromptBarRequestsMixin
from ._prompt_bar_save_xprompt import PromptBarSaveXpromptMixin
from ._prompt_bar_snippet_pane import PromptBarSnippetPaneMixin
from ._prompt_bar_stash import PromptBarStashMixin
from ._prompt_bar_submit import PromptBarSubmitMixin
from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.tui.actions.agents._types import (
        ApprovePromptContext,
        PlanFeedbackContext,
    )


class PromptBarMixin(
    PromptBarMountMixin,
    PromptBarSubmitMixin,
    PromptBarStashMixin,
    PromptBarSaveXpromptMixin,
    PromptBarSnippetPaneMixin,
    PromptBarMiniXPromptPaneMixin,
    PromptBarRequestsMixin,
    PromptBarMemoryPanelMixin,
    PromptBarSnippetsPanelMixin,
):
    """Mixin providing prompt input bar management and event handlers."""

    _prompt_context: PromptContext | None = None
    _plan_feedback_context: PlanFeedbackContext | None
    _approve_prompt_context: ApprovePromptContext | None = None
