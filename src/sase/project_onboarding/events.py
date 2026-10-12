"""NDJSON onboarding events for CLI apply and TUI log tailing."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
import sys
from typing import Any, TextIO

_PLAN_EVENT = "plan"
_STEP_EVENT = "step"
_RESULT_EVENT = "result"
_SUPPORTED_EVENTS = frozenset({_PLAN_EVENT, _STEP_EVENT, _RESULT_EVENT})
_RESULT_STATUSES = frozenset({"ok", "partial", "failed", "blocked"})
_STEP_STATUSES = frozenset({"running", "done", "failed"})

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def emit_event(event: Mapping[str, Any], *, file: TextIO | None = None) -> None:
    """Write one NDJSON event line to *file* (stdout by default)."""

    payload = {str(key): value for key, value in dict(event).items()}
    kind = str(payload.get("event") or "")
    if kind not in _SUPPORTED_EVENTS:
        raise ValueError(f"unsupported onboarding event: {kind!r}")
    stream = sys.stdout if file is None else file
    stream.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    stream.flush()


def parse_event_line(line: str) -> dict[str, Any] | None:
    """Return a supported event dict, or ``None`` for raw or malformed lines.

    Unknown event kinds, truncated JSON, and non-objects are tolerated so a
    TUI tailer can keep the original log line without crashing.
    """

    text = line.strip()
    if not text:
        return None
    try:
        raw = json.loads(text)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    kind = raw.get("event")
    if kind not in _SUPPORTED_EVENTS:
        return None
    if kind == _PLAN_EVENT and not isinstance(raw.get("plan"), dict):
        return None
    if kind == _STEP_EVENT:
        if not str(raw.get("id") or "").strip():
            return None
        status = str(raw.get("status") or "")
        if status and status not in _STEP_STATUSES:
            return None
    if kind == _RESULT_EVENT:
        status = str(raw.get("status") or "")
        if status not in _RESULT_STATUSES:
            return None
    return _sanitize_event(raw)


def _sanitize_event(raw: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            cleaned[str(key)] = _CONTROL_RE.sub("", value)
        else:
            cleaned[str(key)] = value
    return cleaned


__all__ = ["emit_event", "parse_event_line"]
