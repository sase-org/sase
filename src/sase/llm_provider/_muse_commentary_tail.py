"""Fail-soft live tail of Muse session-log commentary.

``muse exec --json`` never puts assistant commentary on stdout. Muse records
each message in the private session log SASE already names with
``--session-id``::

    $XDG_DATA_HOME/muse/sessions/YYYY/MM/DD/<session-id>/session.jsonl

This module tails that file while the process runs and invokes a callback for
every accepted ``phase == "commentary"`` message. The callback is display-only:
callers must not feed commentary into returned content, salvage buffers, or
host finalizers. Every public method swallows its own errors so a missing,
unreadable, or surprising log cannot fail the run.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, BinaryIO

from ._muse_session_usage import MUSE_SESSION_PAYLOAD_TYPE, find_muse_session_log
from ._tool_call_io import append_tool_call_collector_diagnostic

# --- Muse session-log commentary vocabulary ---------------------------
# Record-shape strings the tail depends on live here so a beta rename is a
# one-line fix rather than a grep.

MUSE_COMMENTARY_TAIL_UNAVAILABLE = "muse_commentary_tail_unavailable"

_EVENT_KIND_ASSISTANT_MESSAGE_COMMITTED = "assistant_message_committed"
_EVENT_PHASE_COMMENTARY = "commentary"
_PAYLOAD_KIND_RUN = "run"
_RECORD_TYPE_RETAINED_FRAME = "retained_frame"
_CHILDREN_FIELD = "children"
_RECORD_JSON_FIELD = "record_json"
_STREAM_FIELD = "stream"
_STREAM_ID_FIELD = "id"
_PAYLOAD_FIELD = "payload"
_PAYLOAD_KIND_FIELD = "kind"
_EVENT_FIELD = "event"
_EVENT_KIND_FIELD = "kind"
_EVENT_PHASE_FIELD = "phase"
_EVENT_TEXT_FIELD = "text"
_EVENT_MESSAGE_ID_FIELD = "message_id"
_PAYLOAD_TYPE_FIELD = "payload_type"

_CAUSE_SESSION_LOG_NOT_FOUND = "session_log_not_found"
_CAUSE_READ_ERROR = "read_error"
_CAUSE_MALFORMED_RECORD = "malformed_record"
_CAUSE_UNEXPECTED_ERROR = "unexpected_error"

_PREFILTER_COMMITTED = b"assistant_message_committed"
_PREFILTER_COMMENTARY = b"commentary"

_TICK_INTERVAL_SECONDS = 0.25
_LOCATE_INTERVAL_SECONDS = 1.0
_MAX_READ_BYTES = 1024 * 1024
_MAX_LINE_BYTES = 4 * 1024 * 1024


class MuseCommentaryTail:
    """Poll a Muse session log for display-only commentary messages."""

    def __init__(
        self,
        session_id: str,
        on_commentary: Callable[[str], None],
        *,
        sessions_root: Path | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._session_id = session_id
        self._on_commentary = on_commentary
        self._sessions_root = sessions_root
        self._clock = clock if clock is not None else time.monotonic
        self._handle: BinaryIO | None = None
        self._buffer = b""
        self._skip_to_newline = False
        self._seen_ids: set[str] = set()
        self._disabled = False
        self._diagnostic_recorded = False
        self._last_tick: float | None = None
        self._last_locate: float | None = None

    def tick(self) -> None:
        """Rate-limited poll of newly appended log bytes. Never raises."""

        def _tick() -> None:
            now = self._clock()
            if (
                self._last_tick is not None
                and now - self._last_tick < _TICK_INTERVAL_SECONDS
            ):
                return
            self._last_tick = now
            self._poll(to_eof=False, force_locate=False)

        self._guarded(_tick)

    def drain(self) -> None:
        """Read the log to EOF, locating immediately if needed. Never raises."""

        def _drain() -> None:
            self._poll(to_eof=True, force_locate=True)

        self._guarded(_drain)

    def finish(self) -> None:
        """Final drain, then close. Reports a missing log once. Never raises."""

        def _finish() -> None:
            if not self._disabled:
                self._poll(to_eof=True, force_locate=True)
                if self._handle is None:
                    self._record_diagnostic(_CAUSE_SESSION_LOG_NOT_FOUND)
            self._close_handle()
            self._disabled = True

        self._guarded(_finish)
        self._close_handle()
        self._disabled = True

    def _guarded(self, fn: Callable[[], None]) -> None:
        if self._disabled:
            return
        try:
            fn()
        except OSError as exc:
            self._record_diagnostic(_CAUSE_READ_ERROR, error=str(exc))
            self._disabled = True
            self._close_handle()
        except Exception as exc:
            self._record_diagnostic(_CAUSE_UNEXPECTED_ERROR, error=str(exc))
            self._disabled = True
            self._close_handle()

    def _poll(self, *, to_eof: bool, force_locate: bool) -> None:
        self._ensure_handle(force_locate=force_locate)
        if self._handle is None:
            return
        self._read_new_bytes(to_eof=to_eof)

    def _ensure_handle(self, *, force_locate: bool) -> None:
        if self._handle is not None:
            return
        now = self._clock()
        if (
            not force_locate
            and self._last_locate is not None
            and now - self._last_locate < _LOCATE_INTERVAL_SECONDS
        ):
            return
        self._last_locate = now
        path = find_muse_session_log(
            self._session_id, sessions_root=self._sessions_root
        )
        if path is None:
            return
        self._handle = path.open("rb", buffering=0)

    def _read_new_bytes(self, *, to_eof: bool) -> None:
        handle = self._handle
        if handle is None:
            return
        remaining: int | None = None if to_eof else _MAX_READ_BYTES
        while remaining is None or remaining > 0:
            size = (
                _MAX_READ_BYTES
                if remaining is None
                else min(_MAX_READ_BYTES, remaining)
            )
            chunk = handle.read(size)
            if not chunk:
                break
            if remaining is not None:
                remaining -= len(chunk)
            self._feed(chunk)

    def _feed(self, data: bytes) -> None:
        if self._skip_to_newline:
            newline_at = data.find(b"\n")
            if newline_at < 0:
                return
            data = data[newline_at + 1 :]
            self._skip_to_newline = False
            self._buffer = b""
        self._buffer += data
        while True:
            newline_at = self._buffer.find(b"\n")
            if newline_at < 0:
                if len(self._buffer) > _MAX_LINE_BYTES:
                    self._buffer = b""
                    self._skip_to_newline = True
                return
            line = self._buffer[:newline_at]
            self._buffer = self._buffer[newline_at + 1 :]
            if len(line) > _MAX_LINE_BYTES:
                continue
            self._consider_line(line)

    def _consider_line(self, line: bytes) -> None:
        if not line:
            return
        if _PREFILTER_COMMITTED not in line or _PREFILTER_COMMENTARY not in line:
            return
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._record_diagnostic(_CAUSE_MALFORMED_RECORD)
            return
        if not isinstance(parsed, Mapping):
            return
        self._handle_parsed(parsed)

    def _handle_parsed(self, record: Mapping[str, Any]) -> None:
        if self._is_retained_frame(record):
            for child in self._iter_child_records(record):
                self._maybe_emit(child)
            return
        self._maybe_emit(record)

    def _is_retained_frame(self, record: Mapping[str, Any]) -> bool:
        if record.get("record_type") == _RECORD_TYPE_RETAINED_FRAME:
            return True
        if record.get(_PAYLOAD_TYPE_FIELD) == _RECORD_TYPE_RETAINED_FRAME:
            return True
        return self._children_of(record) is not None

    def _children_of(self, record: Mapping[str, Any]) -> list[Any] | None:
        for container in (record, record.get(_PAYLOAD_FIELD)):
            if not isinstance(container, Mapping):
                continue
            children = container.get(_CHILDREN_FIELD)
            if not isinstance(children, list) or not children:
                continue
            first = children[0]
            if isinstance(first, Mapping) and _RECORD_JSON_FIELD in first:
                return children
        return None

    def _iter_child_records(self, record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        children = self._children_of(record) or []
        decoded: list[Mapping[str, Any]] = []
        for child in children:
            if not isinstance(child, Mapping):
                continue
            raw = child.get(_RECORD_JSON_FIELD)
            if not isinstance(raw, str):
                continue
            try:
                nested = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._record_diagnostic(_CAUSE_MALFORMED_RECORD)
                continue
            if isinstance(nested, Mapping):
                decoded.append(nested)
        return decoded

    def _maybe_emit(self, record: Mapping[str, Any]) -> None:
        if record.get(_PAYLOAD_TYPE_FIELD) != MUSE_SESSION_PAYLOAD_TYPE:
            return
        stream = record.get(_STREAM_FIELD)
        if not isinstance(stream, Mapping):
            return
        if stream.get(_STREAM_ID_FIELD) != self._session_id:
            return
        payload = record.get(_PAYLOAD_FIELD)
        if not isinstance(payload, Mapping):
            return
        if payload.get(_PAYLOAD_KIND_FIELD) != _PAYLOAD_KIND_RUN:
            return
        event = payload.get(_EVENT_FIELD)
        if not isinstance(event, Mapping):
            return
        if event.get(_EVENT_KIND_FIELD) != _EVENT_KIND_ASSISTANT_MESSAGE_COMMITTED:
            return
        if event.get(_EVENT_PHASE_FIELD) != _EVENT_PHASE_COMMENTARY:
            return
        text = event.get(_EVENT_TEXT_FIELD)
        if not isinstance(text, str):
            return
        stripped = text.strip()
        if not stripped:
            return
        message_id = event.get(_EVENT_MESSAGE_ID_FIELD)
        if isinstance(message_id, str) and message_id:
            if message_id in self._seen_ids:
                return
            self._seen_ids.add(message_id)
        self._on_commentary(stripped)

    def _record_diagnostic(self, cause: str, *, error: str | None = None) -> None:
        if self._diagnostic_recorded:
            return
        self._diagnostic_recorded = True
        extra: dict[str, Any] = {
            "session_id": self._session_id,
            "cause": cause,
        }
        if error:
            extra["error"] = error
        try:
            append_tool_call_collector_diagnostic(
                os.environ.get("SASE_ARTIFACTS_DIR"),
                reason=MUSE_COMMENTARY_TAIL_UNAVAILABLE,
                extra=extra,
            )
        except Exception:
            pass

    def _close_handle(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.close()
        except OSError:
            pass


__all__ = ["MUSE_COMMENTARY_TAIL_UNAVAILABLE", "MuseCommentaryTail"]
