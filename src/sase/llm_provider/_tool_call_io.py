"""JSONL writing and diagnostics for tool-call artifacts."""

from __future__ import annotations

import fcntl
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._tool_call_common import preview_text


def append_tool_call_collector_diagnostic(
    artifacts_dir: str | None,
    *,
    reason: str,
    raw_preview: str = "",
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Append a single line to ``tool_calls_writer_errors.jsonl``.

    Public entry point used by the SASE tool-call hook collector (and other
    runtime-provider glue) to record best-effort diagnostics without raising
    from the caller. A missing ``artifacts_dir`` is treated as a no-op.
    """
    if not artifacts_dir:
        return
    record: dict[str, Any] = {
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "reason": reason,
    }
    if raw_preview:
        record["raw_preview"] = preview_text(raw_preview, 240)
    if extra:
        for key, value in extra.items():
            if isinstance(value, str):
                record[key] = preview_text(value, 240)
            else:
                record[key] = value
    try:
        _append_jsonl(Path(artifacts_dir) / "tool_calls_writer_errors.jsonl", record)
    except Exception:
        pass


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with open(lock_path, "a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            with open(path, "a", encoding="utf-8") as output_file:
                json.dump(record, output_file, sort_keys=True)
                output_file.write("\n")
                output_file.flush()
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _append_writer_diagnostic(
    artifacts_dir: str,
    event: Mapping[str, Any],
    exc: Exception,
) -> None:
    try:
        event_label = (
            event.get("type")
            or event.get("hook_event")
            or event.get("hook_event_name")
            or ""
        )
        diagnostic = {
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "error": preview_text(str(exc), 240),
            "event": preview_text(str(event_label), 80),
        }
        _append_jsonl(
            Path(artifacts_dir) / "tool_calls_writer_errors.jsonl", diagnostic
        )
    except Exception:
        pass


append_jsonl = _append_jsonl
append_writer_diagnostic = _append_writer_diagnostic
