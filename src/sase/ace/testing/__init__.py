"""Playwright-inspired testing DSL for the ace TUI."""

from ._startup import (
    _plugins_browser_pane as _plugins_browser_pane,
    _stall_watchdog as _stall_watchdog,
)
from .ace_page import AcePage, AceStartupPolicy
from .editors import PromptPage, VimEditorPage
from .fixtures import DEFAULT_PATCHES, make_changespec, make_patch  # legacy alias
from .prompt_document import set_agent_prompt_document
from .wait import wait_for

DEFAULT_CHANGESPECS = DEFAULT_PATCHES  # legacy compatibility alias

__all__ = [
    "DEFAULT_PATCHES",
    "DEFAULT_CHANGESPECS",  # legacy compatibility alias
    "AcePage",
    "AceStartupPolicy",
    "PromptPage",
    "VimEditorPage",
    "make_changespec",  # legacy compatibility alias
    "make_patch",
    "set_agent_prompt_document",
    "wait_for",
]
