"""Submission, cancellation, and snippet behavior for PromptInputBar."""

from __future__ import annotations

from sase.ace.tui.widgets._prompt_input_bar_cancel_actions import (
    PromptInputBarCancelActionsMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_submission_actions import (
    PromptInputBarSubmissionActionsMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_target_actions import (
    PromptInputBarTargetActionsMixin,
)


class PromptInputBarActionsMixin(
    PromptInputBarSubmissionActionsMixin,
    PromptInputBarCancelActionsMixin,
    PromptInputBarTargetActionsMixin,
):
    """Compose prompt submit, cancel, and targeted insertion actions."""
