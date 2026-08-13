"""Compatibility exports for agent prompt-panel display helpers."""

from __future__ import annotations

from ._agent_display_content import (
    _PHASE_LABELS,
    get_phase_label,
    get_prompt_content,
    render_agent_reply_content,
    render_attempt_divider,
    render_phase_divider,
    render_timestamp_divider,
)
from ._agent_display_header import (
    _UNASSIGNED_AGENT_NAME_DISPLAY,
    build_header_text,
)
from ._agent_display_header_summary import (
    _DETAIL_HEADER_SUMMARY_CACHE_MAX_ENTRIES,
    DetailHeaderSummaryCacheEntry,
    build_detail_header_summary,
    cache_detail_header_summary,
    clear_detail_header_summary_cache,
    get_cached_detail_header_summary,
    publish_opened_workspaces_cache,
    should_refresh_detail_header_summary,
    time,
)
from ._agent_display_state import (
    ALL_DETAIL_CONTEXT_LANES,
    AgentHintRender,
    DetailContextLane,
    DetailHeaderSummary,
    HeaderHintState,
)
from ._helpers import load_xprompts_used

_DetailHeaderSummary = DetailHeaderSummary
_DetailHeaderSummaryCacheEntry = DetailHeaderSummaryCacheEntry

__all__ = [
    "ALL_DETAIL_CONTEXT_LANES",
    "DetailContextLane",
    "DetailHeaderSummary",
    "DetailHeaderSummaryCacheEntry",
    "AgentHintRender",
    "HeaderHintState",
    "_DETAIL_HEADER_SUMMARY_CACHE_MAX_ENTRIES",
    "_DetailHeaderSummary",
    "_DetailHeaderSummaryCacheEntry",
    "_PHASE_LABELS",
    "_UNASSIGNED_AGENT_NAME_DISPLAY",
    "build_detail_header_summary",
    "build_header_text",
    "cache_detail_header_summary",
    "clear_detail_header_summary_cache",
    "get_cached_detail_header_summary",
    "get_phase_label",
    "get_prompt_content",
    "load_xprompts_used",
    "publish_opened_workspaces_cache",
    "render_agent_reply_content",
    "render_attempt_divider",
    "render_phase_divider",
    "render_timestamp_divider",
    "should_refresh_detail_header_summary",
    "time",
]
