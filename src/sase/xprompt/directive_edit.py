"""Pure text helpers for rewriting launch-property xprompt directives."""

from __future__ import annotations

from ._directive_edit_identity import (
    demote_prompt_clan_declaration,
    prompt_declares_clan,
    rewrite_prompt_clan_member_name,
    rewrite_prompt_agent_session_member_name,
    set_prompt_clan_tribe,
    set_prompt_name,
    set_prompt_tribe,
)
from ._tab_inheritance import (
    SASE_AGENT_TAB_ENV,
    TabDirectiveScan,
    apply_inherited_agent_tab,
    inherited_agent_tab,
    scan_tab_directive,
    set_agent_tab_directive,
)
from ._directive_edit_model import set_prompt_model
from ._directive_edit_wait import (
    AutoMode,
    PromptWaitDirective,
    set_prompt_auto_mode,
    set_prompt_queue,
    set_prompt_wait,
    set_prompt_wait_and_queue,
)

__all__ = [
    "AutoMode",
    "PromptWaitDirective",
    "SASE_AGENT_TAB_ENV",
    "TabDirectiveScan",
    "apply_inherited_agent_tab",
    "demote_prompt_clan_declaration",
    "inherited_agent_tab",
    "prompt_declares_clan",
    "rewrite_prompt_clan_member_name",
    "rewrite_prompt_agent_session_member_name",
    "scan_tab_directive",
    "set_agent_tab_directive",
    "set_prompt_auto_mode",
    "set_prompt_clan_tribe",
    "set_prompt_model",
    "set_prompt_name",
    "set_prompt_queue",
    "set_prompt_tribe",
    "set_prompt_wait",
    "set_prompt_wait_and_queue",
]
