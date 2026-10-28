"""In-memory TUI action counters flushed by a daemon thread.

Stdlib only on the event-loop path: :func:`bump` does no I/O, allocating
nothing but a dict entry. A daemon thread named ``sase-footprint-flusher``
wakes every 60 s; when counters are dirty it swaps the dict, writes one
aggregated spool line per ``(feature_id, via)`` plus one ``probe: tui``
line via :mod:`sase.footprint._spool`, and re-reads the mode and
generation files. When the mode is ``off`` or the generation changed since
the counts began, the batch is discarded.

Follows the shape of ``src/sase/telemetry/_registry.py`` (``_start_flusher``,
swap-and-drain, after-fork reset).
"""

from __future__ import annotations

import os
import threading
from datetime import date

from sase.footprint import ids
from sase.footprint.paths import effective_mode, generation_path

FLUSH_INTERVAL_S = 60.0
FLUSH_THREAD_NAME = "sase-footprint-flusher"

_TUI_VIAS = frozenset({"key", "mouse", "palette", "mode"})

_LOCK = threading.Lock()
_START_LOCK = threading.Lock()
_COUNTS: dict[tuple[str, str], int] = {}
_ACTOR: str | None = None
_PID: int | None = None
_START_GENERATION: str | None = None
_GENERATION_LOADED = False
_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def bump(feature_id: str, via: str) -> None:
    """Count one TUI hit. The only call allowed on the event loop.

    Never performs I/O and never raises: validation failures and the
    ``off`` switch simply skip the hit. Starts the daemon flusher lazily
    on the first hit.
    """
    if os.environ.get("SASE_FOOTPRINT") == "off":
        return
    if not isinstance(feature_id, str) or not isinstance(via, str):
        return
    if via not in _TUI_VIAS:
        return
    pid = os.getpid()
    global _PID
    if _PID is None:
        _PID = pid
    elif _PID != pid:
        _reset_after_fork()
    if not ids.is_valid_feature_id(feature_id):
        collapsed = _collapse(feature_id, via)
        if collapsed is None:
            return
        feature_id = collapsed
    if feature_id in ids.NAVIGATION_ACTIONS:
        return
    _ensure_flusher()
    with _LOCK:
        key = (feature_id, via)
        _COUNTS[key] = _COUNTS.get(key, 0) + 1


def flush_now(timeout: float = 0.2) -> None:
    """Write pending counts synchronously. Used at TUI exit.

    ``timeout`` is accepted for the phase contract; the write is one
    ``O_APPEND`` batch and returns well within it. Never raises.
    """
    del timeout
    try:
        batch = _drain()
        if not batch:
            return
        _write_batch(batch)
    except Exception:
        return


def _collapse(feature_id: str, via: str) -> str | None:
    """Collapse an invalid ID to its namespace's ``~other`` sentinel."""
    try:
        namespace, _ = feature_id.split(":", 1)
    except ValueError:
        return None
    if namespace not in ids.NAMESPACES:
        return None
    del via
    return ids.other_id(namespace)


def _ensure_flusher() -> None:
    """Start the daemon flush thread once per process."""
    global _THREAD
    thread = _THREAD
    if thread is not None and thread.is_alive():
        return
    with _START_LOCK:
        thread = _THREAD
        if thread is not None and thread.is_alive():
            return
        _STOP.clear()
        _THREAD = threading.Thread(
            target=_flusher_loop,
            name=FLUSH_THREAD_NAME,
            daemon=True,
        )
        _THREAD.start()


def _flusher_loop() -> None:
    global _START_GENERATION, _GENERATION_LOADED
    _START_GENERATION = _read_generation()
    _GENERATION_LOADED = True
    while not _STOP.wait(FLUSH_INTERVAL_S):
        try:
            if os.getpid() != _PID:
                return
            batch = _drain()
            if batch:
                _write_batch(batch)
            else:
                _START_GENERATION = _read_generation()
        except Exception:
            continue


def _drain() -> dict[tuple[str, str], int]:
    with _LOCK:
        if not _COUNTS:
            return {}
        batch = dict(_COUNTS)
        _COUNTS.clear()
        return batch


def _write_batch(batch: dict[tuple[str, str], int]) -> None:
    """Classify the actor once, enforce mode/generation, append lines."""
    from sase.footprint._actor import classify_actor
    from sase.footprint._spool import append_lines

    global _ACTOR, _START_GENERATION
    if _ACTOR is None:
        actor, _ = classify_actor()
        _ACTOR = (
            actor if actor in ("agent", "automation", "human", "unknown") else "unknown"
        )
    mode = effective_mode()
    if mode not in ("local", "test"):
        _START_GENERATION = _read_generation()
        return
    generation = _read_generation()
    if _GENERATION_LOADED and generation != _START_GENERATION:
        _START_GENERATION = generation
        return
    _START_GENERATION = generation
    day = date.today().isoformat()
    version = _safe_version()
    lines = [
        f'{{"s":1,"d":"{day}","f":"{feature}","a":"{_ACTOR}",'
        f'"v":"{via}","o":"ok","n":{count},"ver":"{version}"}}'
        for (feature, via), count in sorted(batch.items())
        if count >= 1
    ]
    if not lines:
        return
    lines.append(f'{{"s":1,"d":"{day}","probe":"tui","ver":"{version}"}}')
    append_lines(tuple(lines), mode=mode, day=day)


def _read_generation() -> str | None:
    try:
        return generation_path().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _safe_version() -> str:
    from sase import __version__

    return "".join(
        character
        for character in __version__
        if character.isascii() and (character.isalnum() or character in ".-+")
    )[:32]


def _reset_after_fork() -> None:
    """Discard inherited counts after a fork; the parent thread is gone."""
    global _PID, _STOP
    _reset_for_tests()
    _PID = os.getpid()
    _STOP = threading.Event()


def _reset_for_tests() -> None:
    """Stop the flusher and clear all state. Tests only."""
    global _ACTOR, _PID, _START_GENERATION, _GENERATION_LOADED, _THREAD
    _STOP.set()
    thread, _THREAD = _THREAD, None
    if thread is not None and thread.is_alive():
        thread.join(timeout=1)
    with _LOCK:
        _COUNTS.clear()
    _ACTOR = None
    _PID = None
    _START_GENERATION = None
    _GENERATION_LOADED = False


__all__ = [
    "FLUSH_INTERVAL_S",
    "FLUSH_THREAD_NAME",
    "bump",
    "flush_now",
]
