"""Install/uninstall wiring and lock-free GC callback for ACE TUI telemetry."""

from __future__ import annotations

import gc
import os
import resource
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ._gc_telemetry_config import (
    ENV_FLUSH_INTERVAL,
    ENV_HEARTBEAT_INTERVAL,
    FLUSH_INTERVAL_S,
    HEARTBEAT_INTERVAL_S,
    UNTAGGED_TRIGGER,
    is_enabled,
)
from ._gc_telemetry_recorder import GCTelemetry, emit_stall_row


class _PendingStart(threading.local):
    """Per-thread in-flight collection state for the ``gc`` callback."""

    start_mono: float | None
    thread: str
    trigger: str
    last_input_mono: float
    start_majflt: int | None

    def __init__(self) -> None:
        self.start_mono = None
        self.thread = ""
        self.trigger = UNTAGGED_TRIGGER
        self.last_input_mono = 0.0
        self.start_majflt = None


_active: GCTelemetry | None = None
_trigger_tag: str = UNTAGGED_TRIGGER
_pending_start = _PendingStart()
_last_input_mono: float = 0.0


def note_last_input_mono(value: float) -> None:
    """Record the monotonic time of the latest user input.

    The GC callback copies this into each pause record. A plain attribute
    write so the interactive path stays lock-free.
    """
    global _last_input_mono
    _last_input_mono = value


def _majflt() -> int | None:
    try:
        return resource.getrusage(resource.RUSAGE_SELF).ru_majflt
    except Exception:
        return None


@contextmanager
def gc_trigger(name: str) -> Iterator[None]:
    """Tag collections running inside the block with ``name``.

    The ``gc.callbacks`` entry copies the current tag into each record.
    Untagged collections record as ``"automatic"``. Nesting restores the
    outer tag on exit.
    """
    global _trigger_tag
    previous = _trigger_tag
    _trigger_tag = name
    try:
        yield
    finally:
        _trigger_tag = previous


def new_app_instance_id() -> str:
    """Mint one short random ID per app instance."""
    return secrets.token_hex(4)


def app_instance_id(app: Any) -> str | None:
    """Return the app instance ID minted at construction, if present."""
    value = getattr(app, "_app_instance_id", None)
    return value if isinstance(value, str) and value else None


def latest_rss_bytes() -> int | None:
    """Return the latest heartbeat RSS sample, without touching ``/proc``."""
    active = _active
    if active is None:
        return None
    return active.latest_rss


def latest_memory_pressure() -> dict[str, int | float | None] | None:
    """Return the latest cached pressure sample without touching ``/proc``."""
    active = _active
    if active is None:
        return None
    return active.memory_pressure_snapshot()


def queue_row(event: str, extra: dict[str, Any]) -> None:
    """Queue an auxiliary telemetry row without doing UI-thread file I/O."""
    active = _active
    if active is not None:
        active.queue_row(event, extra)


def recent_collections(since_mono: float) -> list[dict[str, Any]]:
    """Return recent collections ending at or after ``since_mono``."""
    active = _active
    if active is None:
        return []
    return active.recent_collections(since_mono)


def _gc_callback(phase: str, info: dict[str, Any]) -> None:
    recorder = _active
    if recorder is None:
        return
    if phase == "start":
        _pending_start.start_mono = time.monotonic()
        _pending_start.thread = threading.current_thread().name
        _pending_start.trigger = _trigger_tag
        _pending_start.last_input_mono = _last_input_mono
        _pending_start.start_majflt = _majflt()
    elif phase == "stop":
        end_mono = time.monotonic()
        start_mono = _pending_start.start_mono
        if start_mono is None:
            start_mono = end_mono
        last_input = _pending_start.last_input_mono
        input_age_s = None
        if last_input > 0.0:
            age = start_mono - last_input
            input_age_s = age if age >= 0.0 else 0.0
        start_maj = _pending_start.start_majflt
        end_maj = _majflt()
        major_faults_delta = None
        if start_maj is not None and end_maj is not None:
            delta = end_maj - start_maj
            major_faults_delta = delta if delta >= 0 else 0
        recorder._record_stop(
            int(info.get("generation", 0)),
            start_mono,
            end_mono,
            _pending_start.thread or threading.current_thread().name,
            _pending_start.trigger,
            int(info.get("collected", 0)),
            int(info.get("uncollectable", 0)),
            input_age_s,
            major_faults_delta,
        )
        _pending_start.start_mono = None
        _pending_start.last_input_mono = 0.0
        _pending_start.start_majflt = None


def emit_row(event: str, extra: dict[str, Any]) -> None:
    """Write one telemetry row on the flush/census path.

    Census and other opt-in rows share the stall JSONL. Core identity
    fields are filled here so callers never clobber ``event``.
    """
    active = _active
    row: dict[str, Any] = {
        "event": event,
        "ts": time.time(),
        "pid": os.getpid(),
        "app_instance_id": None if active is None else active.instance_id,
    }
    for key, value in extra.items():
        row.setdefault(key, value)
    if active is not None:
        active._emit(row)
    else:
        emit_stall_row(row)


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def install_gc_telemetry(
    app: Any = None,
    *,
    flush_interval_s: float | None = None,
    heartbeat_interval_s: float | None = None,
) -> GCTelemetry | None:
    """Install the recorder and flush thread; return the handle or ``None``.

    Safe to call twice: a second install while one is active returns the
    active handle. Never raises: any failure returns ``None``.
    """
    global _active
    try:
        if not is_enabled():
            return None
        callbacks = getattr(gc, "callbacks", None)
        if callbacks is None:
            return None
        active = _active
        if active is not None:
            if _gc_callback not in callbacks:
                callbacks.append(_gc_callback)
            return active
        instance_id = app_instance_id(app) if app is not None else None
        if instance_id is None:
            instance_id = new_app_instance_id()
            if app is not None:
                try:
                    app._app_instance_id = instance_id
                except (AttributeError, TypeError):
                    pass
        telemetry = GCTelemetry(
            app_instance_id=instance_id,
            flush_interval_s=(
                flush_interval_s
                if flush_interval_s is not None
                else _positive_float_env(ENV_FLUSH_INTERVAL, FLUSH_INTERVAL_S)
            ),
            heartbeat_interval_s=(
                heartbeat_interval_s
                if heartbeat_interval_s is not None
                else _positive_float_env(ENV_HEARTBEAT_INTERVAL, HEARTBEAT_INTERVAL_S)
            ),
        )
        callbacks.append(_gc_callback)
        _active = telemetry
        telemetry.start()
        return telemetry
    except Exception:
        return None


def uninstall_gc_telemetry(handle: GCTelemetry | None = None) -> None:
    """Stop the flush thread and remove the callback we installed.

    Only our own callback is removed, so ``gc.callbacks`` is left exactly
    as it was found.
    """
    global _active
    target = handle if handle is not None else _active
    if target is None:
        return
    if _active is target:
        _active = None
    try:
        target.stop()
    except Exception:
        pass
    try:
        callbacks = getattr(gc, "callbacks", None)
        if callbacks is not None and _gc_callback in callbacks:
            callbacks.remove(_gc_callback)
    except Exception:
        pass
