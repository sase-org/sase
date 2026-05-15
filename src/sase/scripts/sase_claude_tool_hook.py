"""SASE tool-call hook collector for Claude PreToolUse/PostToolUse hooks.

Reads one hook JSON object from stdin and appends a normalized schema-v3
record to ``$SASE_ARTIFACTS_DIR/tool_calls.jsonl``. The collector is designed
to be non-blocking for the agent: malformed input, missing environment, or
write failures result in a best-effort diagnostic and an exit code of 0 so
Claude does not surface the hook as a tool-call failure.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from typing import Any

from sase.llm_provider._tool_calls import (
    append_claude_hook_tool_call_event,
    append_tool_call_collector_diagnostic,
)


def main(argv: list[str] | None = None) -> int:
    del argv

    raw = _read_stdin()
    if not raw.strip():
        return 0

    payload = _parse_payload(raw)
    if payload is None:
        append_tool_call_collector_diagnostic(
            os.environ.get("SASE_ARTIFACTS_DIR"),
            reason="invalid_json",
            raw_preview=raw,
        )
        return 0

    try:
        append_claude_hook_tool_call_event(payload)
    except Exception as exc:
        append_tool_call_collector_diagnostic(
            os.environ.get("SASE_ARTIFACTS_DIR"),
            reason="collector_exception",
            raw_preview=raw,
            extra={"error": str(exc)},
        )
    return 0


def _read_stdin() -> str:
    try:
        return sys.stdin.read()
    except Exception:
        return ""


def _parse_payload(raw: str) -> Mapping[str, Any] | None:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, Mapping) else None


if __name__ == "__main__":
    raise SystemExit(main())
