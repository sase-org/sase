"""Pure text helpers for rewriting launch-property xprompt directives."""

from __future__ import annotations

from ._directive_edit_identity import (
    demote_prompt_clan_declaration,
    prompt_declares_clan,
    rewrite_prompt_clan_member_name,
    rewrite_prompt_family_member_name,
    set_prompt_clan_tribe,
    set_prompt_name,
    set_prompt_tribe,
)
from ._directive_edit_model import set_prompt_model
from ._directive_edit_wait import (
    AutoMode,
    PromptWaitDirective,
    set_prompt_auto_mode,
    set_prompt_wait,
)

__all__ = [
    "AutoMode",
    "PromptWaitDirective",
    "demote_prompt_clan_declaration",
    "prompt_declares_clan",
    "rewrite_prompt_clan_member_name",
    "rewrite_prompt_family_member_name",
    "set_prompt_auto_mode",
    "set_prompt_clan_tribe",
    "set_prompt_model",
    "set_prompt_name",
    "set_prompt_tribe",
    "set_prompt_wait",
]
