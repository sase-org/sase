"""Prompt ``g`` prefix dispatch and hint metadata for PromptInputBar.

Public facade: the implementation lives in sibling
``_prompt_input_bar_g_prefix_*`` modules; this file re-exports the name
that callers historically import from
``_prompt_input_bar_g_prefix_actions``.
"""

from __future__ import annotations

from sase.ace.tui.widgets._prompt_input_bar_g_prefix_dispatch import (
    PromptInputBarGPrefixDispatchMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_g_prefix_hint_metadata import (
    PromptInputBarGPrefixHintMetadataMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_g_prefix_panel_actions import (
    PromptInputBarGPrefixPanelActionsMixin,
)

__all__ = ["PromptInputBarGPrefixActionsMixin"]


class PromptInputBarGPrefixActionsMixin(
    PromptInputBarGPrefixDispatchMixin,
    PromptInputBarGPrefixPanelActionsMixin,
    PromptInputBarGPrefixHintMetadataMixin,
):
    """Prompt ``g`` prefix keymaps and hint entry generation."""
