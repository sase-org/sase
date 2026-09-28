"""``⚒ Runs`` deck view with off-thread node-summary and block loaders.

Facade preserving the original :mod:`view` public import path. The
implementation now lives in :mod:`messages`, :mod:`rows`,
:mod:`loader`, :mod:`widget`, and :mod:`widget_live`; this module only
re-exports the public names.
"""

from __future__ import annotations

from .loader import load_tool_runs_deck
from .messages import ToolRunsDeckLoaded, ToolRunsDeckLoadResult
from .rows import tool_runs_cache_signature, tool_runs_rows_for_document
from .widget import ToolRunsDeckView

__all__ = [
    "ToolRunsDeckLoaded",
    "ToolRunsDeckLoadResult",
    "ToolRunsDeckView",
    "load_tool_runs_deck",
    "tool_runs_cache_signature",
    "tool_runs_rows_for_document",
]
