"""Prompt input bar management and event handlers for agent workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._prompt_bar_mount import PromptBarMountMixin
from ._prompt_bar_requests import PromptBarRequestsMixin
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
    PromptBarRequestsMixin,
):
    """Mixin providing prompt input bar management and event handlers."""

    _prompt_context: PromptContext | None = None
    _plan_feedback_context: PlanFeedbackContext | None
    _approve_prompt_context: ApprovePromptContext | None = None

    _TRIVIAL_PROMPT_PATTERNS = frozenset({".", ".x"})
