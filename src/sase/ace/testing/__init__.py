"""Playwright-inspired testing DSL for the ace TUI."""

from ._startup import (
    _plugins_browser_pane as _plugins_browser_pane,
    _stall_watchdog as _stall_watchdog,
)
from .ace_page import AcePage, AceStartupPolicy
from .editors import PromptPage, VimEditorPage
from .fixtures import DEFAULT_CHANGESPECS, make_changespec

__all__ = [
    "DEFAULT_CHANGESPECS",
    "AcePage",
    "AceStartupPolicy",
    "PromptPage",
    "VimEditorPage",
    "make_changespec",
]
