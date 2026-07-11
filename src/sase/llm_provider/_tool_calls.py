"""Runtime-neutral tool-call artifact writers.

Claude, Codex, Qwen, and OpenCode write the same normalized artifact
shape from their provider stream parsers. Claude schema-v3 hook payload support
is retained as a legacy compatibility surface for old artifacts/tests; new
Claude provider runs use assistant/user ``stream-json`` events and do not
install tool-call hooks.

Implementation lives in focused private modules; this module preserves the
historical import surface used by provider glue and tests.
"""

from __future__ import annotations

from ._tool_call_claude import (
    HOOK_COLLECTOR_EVENTS,
    append_claude_hook_tool_call_event,
    append_claude_tool_call_event,
    normalize_claude_hook_payload as _normalize_claude_hook_payload,
    normalize_claude_stream_event as _normalize_claude_stream_event,
)
from ._tool_call_codex import (
    append_codex_tool_call_event,
    normalize_codex_tool_call_event as _normalize_codex_tool_call_event,
)
from ._tool_call_qwen import (
    append_qwen_tool_call_event,
    normalize_qwen_tool_call_event as _normalize_qwen_tool_call_event,
)
from ._subprocess_agy import append_agy_tool_call_events
from ._tool_call_common import (
    HOOK_SCHEMA_VERSION as _HOOK_SCHEMA_VERSION,
    PREVIEW_LIMIT as _PREVIEW_LIMIT,
    SCHEMA_VERSION as _SCHEMA_VERSION,
    TOOL_CALL_RECORD_OPTIONAL_FIELDS as _TOOL_CALL_RECORD_OPTIONAL_FIELDS,
    TOOL_CALL_RECORD_REQUIRED_FIELDS as _TOOL_CALL_RECORD_REQUIRED_FIELDS,
    summarize_tool_input as _summarize_tool_input,
)
from ._tool_call_io import (
    append_tool_call_collector_diagnostic,
    append_jsonl as _append_jsonl,
    append_writer_diagnostic as _append_writer_diagnostic,
)
from ._tool_call_finalize import finalize_pending_tool_calls

__all__ = [
    "HOOK_COLLECTOR_EVENTS",
    "_HOOK_SCHEMA_VERSION",
    "_PREVIEW_LIMIT",
    "_SCHEMA_VERSION",
    "_TOOL_CALL_RECORD_OPTIONAL_FIELDS",
    "_TOOL_CALL_RECORD_REQUIRED_FIELDS",
    "_append_jsonl",
    "_append_writer_diagnostic",
    "_normalize_claude_hook_payload",
    "_normalize_claude_stream_event",
    "_normalize_codex_tool_call_event",
    "_normalize_qwen_tool_call_event",
    "_summarize_tool_input",
    "append_claude_hook_tool_call_event",
    "append_claude_tool_call_event",
    "append_agy_tool_call_events",
    "append_codex_tool_call_event",
    "append_qwen_tool_call_event",
    "append_tool_call_collector_diagnostic",
    "finalize_pending_tool_calls",
]
