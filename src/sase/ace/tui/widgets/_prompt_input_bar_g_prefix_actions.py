"""Prompt ``g`` prefix dispatch and hint metadata for PromptInputBar."""

from __future__ import annotations

from sase.ace.tui.widgets._prompt_input_bar_g_prefix_continuations import (
    PromptGPrefixContinuationsMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_g_prefix_dispatch import (
    PromptGPrefixDispatchMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_g_prefix_metadata import (
    PromptGPrefixMetadataMixin,
)

__all__ = ["PromptInputBarGPrefixActionsMixin"]


class PromptInputBarGPrefixActionsMixin(
    PromptGPrefixDispatchMixin,
    PromptGPrefixContinuationsMixin,
    PromptGPrefixMetadataMixin,
):
    """Prompt ``g`` prefix keymaps and hint entry generation."""
