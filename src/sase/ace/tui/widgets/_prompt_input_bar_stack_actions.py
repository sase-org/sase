"""Stack navigation and structural actions for PromptInputBar."""

from __future__ import annotations

from sase.ace.tui.widgets._prompt_input_bar_g_prefix_actions import (
    PromptInputBarGPrefixActionsMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_local_xprompt_actions import (
    PromptInputBarLocalXPromptActionsMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
    PromptGPrefixHintEntry,
    StashedPromptPane,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_navigation import (
    PromptInputBarStackNavigationMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_stash_actions import (
    PromptInputBarStashActionsMixin,
)

__all__ = [
    "PromptGPrefixHintEntry",
    "PromptInputBarStackActionsMixin",
    "StashedPromptPane",
]


class PromptInputBarStackActionsMixin(
    PromptInputBarGPrefixActionsMixin,
    PromptInputBarStackNavigationMixin,
    PromptInputBarStashActionsMixin,
    PromptInputBarLocalXPromptActionsMixin,
):
    """Prompt stack keymaps and structural actions."""
