"""Fold-aware content sections for synthetic agent-clan detail rows."""

from __future__ import annotations

from ._agent_display_clan_sections_common import ClanMemberHintWorkspace
from ._agent_display_clan_sections_context import (
    append_context_section,
    disk_section_loaded,
    minimal_context_lanes,
)
from ._agent_display_clan_sections_slow import append_slow_tool_calls_section
from ._agent_display_clan_sections_text import (
    append_errors_section,
    append_text_section,
    append_variables_section,
)

__all__ = [
    "ClanMemberHintWorkspace",
    "append_context_section",
    "append_errors_section",
    "append_slow_tool_calls_section",
    "append_text_section",
    "append_variables_section",
    "disk_section_loaded",
    "minimal_context_lanes",
]
