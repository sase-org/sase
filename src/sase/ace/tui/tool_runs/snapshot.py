"""App-level ToolRun glance snapshot service (plan §3.5.1).

Holds one immutable :class:`_ToolRunGlanceSnapshot` (runs by attribution key,
``silent_after_s``, store token, and a load generation). Loads run off the
event loop through ``asyncio.to_thread(tool_run_live_glance)``; render paths
read the in-memory snapshot plus ``now`` and never touch SQLite.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_TOOL_RUNS_DISABLED_REASON: str | None = None
_TOOL_RUNS_DISABLED_LOGGED = False
_snapshot_lock = threading.Lock()
_current_snapshot: _ToolRunGlanceSnapshot | None = None


@dataclass(frozen=True)
class _ToolRunGlanceSnapshot:
    """One immutable glance load: every unsettled run on the machine."""

    runs: tuple[Any, ...] = ()
    silent_after_s: int = 60
    store_token: Any | None = None
    generation: int = 0
    fetched_at_mono: float = 0.0
    truncated: bool = False
    store_exists: bool = True

    @property
    def has_live_runs(self) -> bool:
        """Return True when the snapshot holds at least one live run."""

        return bool(self.runs)


def get_snapshot() -> _ToolRunGlanceSnapshot | None:
    """Return the current app-level glance snapshot, if any."""

    with _snapshot_lock:
        return _current_snapshot


def _set_snapshot(snapshot: _ToolRunGlanceSnapshot | None) -> None:
    """Publish *snapshot* as the current app-level glance snapshot."""

    global _current_snapshot
    with _snapshot_lock:
        _current_snapshot = snapshot


def _build_snapshot(
    runs: tuple[Any, ...] | list[Any],
    *,
    silent_after_s: int = 60,
    store_token: Any | None = None,
    generation: int = 0,
    truncated: bool = False,
    store_exists: bool = True,
    fetched_at_mono: float | None = None,
) -> _ToolRunGlanceSnapshot:
    """Build an immutable snapshot from one glance load."""

    return _ToolRunGlanceSnapshot(
        runs=tuple(runs),
        silent_after_s=int(silent_after_s or 60),
        store_token=store_token,
        generation=int(generation),
        fetched_at_mono=(
            float(fetched_at_mono) if fetched_at_mono is not None else time.monotonic()
        ),
        truncated=bool(truncated),
        store_exists=bool(store_exists),
    )


def tool_runs_disabled_reason() -> str | None:
    """Return why ToolRun surfaces are disabled for the session, if any."""

    return _TOOL_RUNS_DISABLED_REASON


def note_tool_runs_disabled(reason: str) -> None:
    """Disable ToolRun surfaces for the session with one log line."""

    global _TOOL_RUNS_DISABLED_REASON, _TOOL_RUNS_DISABLED_LOGGED
    _TOOL_RUNS_DISABLED_REASON = reason
    if _TOOL_RUNS_DISABLED_LOGGED:
        return
    _TOOL_RUNS_DISABLED_LOGGED = True
    log.warning("ToolRun surfaces disabled for session: %s", reason)


def load_glance_blocking(
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> _ToolRunGlanceSnapshot | None:
    """Load one glance snapshot on a worker thread; never raise.

    A busy or locked store, a newer schema, or a thread error keeps the
    last snapshot (returns None). A missing binding disables ToolRun
    surfaces for the session with one log line.
    """

    try:
        from sase.core.tool_run import tool_run_live_glance
    except Exception as exc:
        note_tool_runs_disabled(f"missing tool_run binding: {exc}")
        return None
    try:
        result = tool_run_live_glance(
            store_path=store_path,
            busy_timeout_ms=busy_timeout_ms,
        )
    except AttributeError as exc:
        # Stale wheel: require_rust_binding raises AttributeError.
        note_tool_runs_disabled(f"missing tool_run_live_glance binding: {exc}")
        return None
    except Exception as exc:
        log.debug("ToolRun glance load failed, keeping last snapshot: %s", exc)
        return None
    try:
        runs = tuple(getattr(result, "runs", ()) or ())
        silent_after_s = int(getattr(result, "silent_after_s", 60) or 60)
        truncated = bool(getattr(result, "truncated", False))
        store_exists = bool(getattr(result, "store_exists", True))
    except Exception as exc:
        log.debug("ToolRun glance decode failed, keeping last snapshot: %s", exc)
        return None
    previous = get_snapshot()
    generation = int(previous.generation) + 1 if previous is not None else 1
    return _build_snapshot(
        runs,
        silent_after_s=silent_after_s,
        store_token=None,
        generation=generation,
        truncated=truncated,
        store_exists=store_exists,
    )


def apply_loaded_snapshot(
    loaded: _ToolRunGlanceSnapshot | None,
    *,
    store_token: Any | None = None,
) -> _ToolRunGlanceSnapshot | None:
    """Publish *loaded* with its store token; None keeps the last snapshot."""

    if loaded is None:
        return get_snapshot()
    if store_token is not None:
        loaded = _ToolRunGlanceSnapshot(
            runs=loaded.runs,
            silent_after_s=loaded.silent_after_s,
            store_token=store_token,
            generation=loaded.generation,
            fetched_at_mono=loaded.fetched_at_mono,
            truncated=loaded.truncated,
            store_exists=loaded.store_exists,
        )
    _set_snapshot(loaded)
    return loaded


@dataclass
class ToolRunsLoadState:
    """Coalescing state for the snapshot worker (one per app)."""

    scheduled: bool = False
    running: bool = False
    pending: bool = False
    source: str = "unknown"
    last_probe_mono: float = 0.0
    last_token: Any | None = None


_TOOL_RUNS_DRIFT_PROBE_MIN_INTERVAL_S = 2.0


def should_probe_drift(now_mono: float, state: ToolRunsLoadState) -> bool:
    """Return True when the stat-only drift probe may run again (≤2 s)."""

    return (now_mono - state.last_probe_mono) >= _TOOL_RUNS_DRIFT_PROBE_MIN_INTERVAL_S


__all__ = [
    "_ToolRunGlanceSnapshot",
    "ToolRunsLoadState",
    "apply_loaded_snapshot",
    "get_snapshot",
    "note_tool_runs_disabled",
    "load_glance_blocking",
    "should_probe_drift",
    "tool_runs_disabled_reason",
]
