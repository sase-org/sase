"""Idle-time full-GC policy for the ACE TUI.

CPython's classic collector fires a stop-the-world gen-2 collection after a
handful of gen-1 collections *and* 25% old-generation growth, which lands
multi-second freezes on the interactive path. This module moves that decision
off the interactive path:

- after startup loads settle and input first goes idle, one ``gc.collect()``
  followed by ``gc.freeze()``, exactly once per app instance (never re-frozen:
  cyclic garbage among frozen objects is never reclaimed);
- ``threshold2`` raised to 10_000 on the classic three-generation collector so
  automatic full collections become a rare backstop;
- tagged full collections only while input is quiet, no prompt is active, and
  a collection is due, with 5-minute and RSS-growth backstops;
- duty-cycle bound: each own full collection's pause (timed with the
  injected clock) defers the next full collection by ``pause * DUTY_FACTOR``
  (clamped to 15 min, floored at 60 s), applied to idle and backstop
  triggers alike;
- freed arenas returned with ``malloc_trim`` on a worker thread.

Every collection runs under :func:`gc_trigger` (from
:mod:`sase.ace.tui.util.gc_telemetry`) so ``tui_gc_pause`` rows carry the
``startup_freeze`` / ``idle`` / ``backstop`` / ``rss_backstop`` trigger and the
watchdog can attribute any resulting hitch. The policy is driven by a 1 s
``set_interval`` whose callback stays thin and synchronous; it never reads
``/proc`` on the UI thread (RSS comes from the telemetry heartbeat sample)
and never auto-installs under the ``sase.ace.testing`` harness. The opt-in
survivor census (``SASE_TUI_GC_CENSUS=1``) needs Python 3.14+; earlier
CPython versions skip ``gc.get_objects()`` and record collected-garbage
types only. Census rows rank types by count and shallow ``sys.getsizeof``
bytes, always emit a watchlist of suspected heap owners, and probe
already-imported snapshot caches so later diet phases can name owners.
"""

from __future__ import annotations

import gc
import logging
import os
import sys
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from textual.screen import ModalScreen
from textual.widgets import Input, TextArea

from sase.ace.tui.util.gc_telemetry import (
    emit_row,
    gc_trigger,
    latest_rss_bytes,
    register_heartbeat_provider,
    unregister_heartbeat_provider,
)
from sase.axe.runner_idle_memory import trim_allocator

log = logging.getLogger(__name__)

ENV_DISABLE = "SASE_TUI_GC_POLICY_DISABLE"
ENV_CENSUS = "SASE_TUI_GC_CENSUS"
TICK_INTERVAL_S = 1.0
IDLE_QUIET_S = 3.0
BACKSTOP_QUIET_S = 3.0
MIN_FULL_INTERVAL_S = 60.0
FULL_BACKSTOP_S = 5 * 60.0
DUTY_FACTOR = 30.0
MAX_DUTY_DELAY_S = 15 * 60.0
RSS_GROWTH_BACKSTOP_BYTES = 500 * 1024 * 1024
GEN1_DUE_COUNT = 100
NONCLASSIC_DUE_S = 120.0
RAISED_THRESHOLD2 = 10_000
TRIM_INTERVAL_S = 10 * 60.0
CENSUS_INTERVAL_S = 10 * 60.0
CENSUS_TOP_N = 40
CENSUS_WATCHLIST: frozenset[str] = frozenset(
    {
        "sase.ace.tui.models.agent.Agent",
        "sase.ace.tui.provider_contract.AceRowHandle",
        "sase.agents.catalog._query.AgentCatalogLinkFacets",
        "sase.artifact_read_log.ArtifactReadEvent",
        "sase.core.agent_scan_wire.AgentArtifactRecordWire",
        "sase.core.artifact_file_types.ArtifactFile",
        "sase.core.bead_touch_index_models.BeadTouch",
        "sase.memory._read_log_models.MemoryReadEvent",
        "sase.notifications.models.Notification",
        "sase.notifications.models.NotificationPlusOne",
        "textual.cache.FIFOCache",
    }
)
TIMER_NAME = "gc-policy"
TRIM_THREAD_NAME = "sase-tui-gc-trim"
HEARTBEAT_PROVIDER_NAME = "gc_policy"
THRESHOLD_RAISED = "raised"
THRESHOLD_UNSUPPORTED = "unsupported"
FULL_GENERATION = 2

_active: GCPolicy | None = None
_trim_worker_lock = threading.Lock()
_trim_worker_event = threading.Event()
_trim_worker_stop = threading.Event()
_trim_worker: threading.Thread | None = None


def is_enabled() -> bool:
    """Return whether the GC policy may install (kill switch aware)."""
    return os.environ.get(ENV_DISABLE) != "1"


def _census_enabled() -> bool:
    """Return whether the opt-in GC census is on (``SASE_TUI_GC_CENSUS=1``)."""
    return os.environ.get(ENV_CENSUS) == "1"


def _survivor_census_safe() -> bool:
    """Return whether ``gc.get_objects()`` is safe to hold during a census.

    On CPython < 3.14, ``gc.get_objects()`` exposes tuples that other threads
    are still building, and holding them makes those threads'
    ``_PyTuple_Resize`` fail with ``SystemError``.
    """
    return sys.version_info >= (3, 14)


def _type_key(obj: object) -> str:
    cls = type(obj)
    module = getattr(cls, "__module__", "") or ""
    qualname = (
        getattr(cls, "__qualname__", None) or getattr(cls, "__name__", None) or "?"
    )
    return f"{module}.{qualname}" if module else str(qualname)


@dataclass(frozen=True)
class _TypeCensus:
    """Ranked type counts plus optional watchlist rows from one object walk."""

    top: list[dict[str, Any]]
    total: int
    watch: list[dict[str, Any]]
    bytes_total: int


def _type_row(name: str, count: int, size: int) -> dict[str, Any]:
    return {"type": name, "count": count, "bytes": int(size)}


def _top_types(
    objects: Iterable[object],
    n: int = CENSUS_TOP_N,
    *,
    watch: frozenset[str] | None = None,
) -> _TypeCensus:
    """Return the *n* most common types, watchlist rows, and shallow bytes."""
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    total = 0
    bytes_total = 0
    for obj in objects:
        total += 1
        try:
            key = _type_key(obj)
        except Exception:
            continue
        counts[key] += 1
        try:
            size = sys.getsizeof(obj)
        except Exception:
            size = 0
        sizes[key] += size
        bytes_total += size
    top = [_type_row(name, count, sizes[name]) for name, count in counts.most_common(n)]
    watched = [
        _type_row(name, counts[name], sizes[name]) for name in sorted(watch or ())
    ]
    return _TypeCensus(
        top=top, total=total, watch=watched, bytes_total=int(bytes_total)
    )


def _cache_event_count(value: Any, attr: str = "events") -> int:
    """Return ``len(value.attr)`` for a snapshot-cache entry, else 0."""
    try:
        events = getattr(value, attr, None)
        if events is None:
            return 0
        return len(events)
    except Exception:
        return 0


def _locked_mapping_items(cache: Any, lock: Any | None = None) -> list[tuple[Any, Any]]:
    """Copy ``cache`` items while holding *lock* or ``cache._lock``."""
    held = lock if lock is not None else getattr(cache, "_lock", None)
    if held is None:
        try:
            return list(OrderedDict.items(cache))
        except Exception:
            entries = getattr(cache, "_entries", None)
            if isinstance(entries, Mapping):
                return list(entries.items())
            return []
    try:
        held.acquire()
    except Exception:
        return []
    try:
        try:
            return list(OrderedDict.items(cache))
        except Exception:
            entries = getattr(cache, "_entries", None)
            if isinstance(entries, Mapping):
                return list(entries.items())
            return []
    finally:
        try:
            held.release()
        except Exception:
            pass


def _snapshot_cache_census(cache: Any) -> dict[str, Any]:
    """Summarize ``ARTIFACT_SNAPSHOT_CACHE`` generations and retained records."""
    items = _locked_mapping_items(cache)
    generations: list[dict[str, Any]] = []
    record_total = 0
    for key, value in items:
        snapshot = value[1] if isinstance(value, tuple) and len(value) >= 2 else None
        records = _cache_event_count(snapshot, "records")
        record_total += records
        key_parts = (
            [str(part) for part in key] if isinstance(key, tuple) else [str(key)]
        )
        generations.append({"key": key_parts, "records": records})
    return {
        "entries": len(items),
        "max_entries": getattr(cache, "_max_entries", None),
        "record_total": record_total,
        "generations": generations,
    }


def _lru_cache_census(cache: Any, *, event_attr: str = "events") -> dict[str, Any]:
    """Summarize a ``BoundedLRUCache`` of snapshot entries."""
    items = _locked_mapping_items(cache)
    event_total = 0
    per_key: list[dict[str, Any]] = []
    for key, value in items:
        count = _cache_event_count(value, event_attr)
        event_total += count
        per_key.append({"key": str(key), "events": count})
    return {
        "entries": len(items),
        "max_entries": getattr(cache, "max_entries", None),
        "event_total": event_total,
        "keys": per_key,
    }


def _index_file_cache_census(cache: Any, lock: Any | None = None) -> dict[str, Any]:
    """Summarize ``_artifact_file_index_cache`` path entries and row counts."""
    items = _locked_mapping_items(cache, lock=lock)
    row_total = 0
    paths: list[dict[str, Any]] = []
    for key, value in items:
        rows = value[1] if isinstance(value, tuple) and len(value) >= 2 else value
        try:
            count = len(rows)
        except Exception:
            count = 0
        row_total += count
        paths.append({"path": str(key), "rows": count})
    return {
        "entries": len(items),
        "row_total": row_total,
        "paths": paths,
    }


def _known_cache_census() -> list[dict[str, Any]]:
    """Probe already-imported module-level caches; never import new modules."""
    probes: tuple[tuple[str, str, str, str], ...] = (
        (
            "sase.ace.tui.models._agent_loader_artifact_cache",
            "ARTIFACT_SNAPSHOT_CACHE",
            "src/sase/ace/tui/models/_agent_loader_artifact_cache.py",
            "snapshot",
        ),
        (
            "sase.core.artifact_file_explicit",
            "_artifact_file_index_cache",
            "src/sase/core/artifact_file_explicit.py",
            "index",
        ),
        (
            "sase.ace.tui.artifact_reads",
            "_artifact_reads_snapshot_cache",
            "src/sase/ace/tui/artifact_reads.py",
            "lru",
        ),
        (
            "sase.ace.tui.memory_reads",
            "_memory_reads_snapshot_cache",
            "src/sase/ace/tui/memory_reads.py",
            "lru",
        ),
        (
            "sase.ace.tui._bead_touches_loader",
            "_bead_touches_snapshot_cache",
            "src/sase/ace/tui/_bead_touches_loader.py",
            "lru",
        ),
        (
            "sase.ace.tui.glossary_reads",
            "_glossary_reads_snapshot_cache",
            "src/sase/ace/tui/glossary_reads.py",
            "lru",
        ),
        (
            "sase.ace.tui.skill_uses",
            "_skill_uses_snapshot_cache",
            "src/sase/ace/tui/skill_uses.py",
            "lru",
        ),
    )
    rows: list[dict[str, Any]] = []
    for module_name, attr, anchor, kind in probes:
        try:
            module = sys.modules.get(module_name)
            if module is None:
                rows.append(
                    {
                        "name": f"{module_name}.{attr}",
                        "anchor": anchor,
                        "imported": False,
                    }
                )
                continue
            cache = getattr(module, attr, None)
            if cache is None:
                rows.append(
                    {
                        "name": f"{module_name}.{attr}",
                        "anchor": anchor,
                        "imported": True,
                        "present": False,
                    }
                )
                continue
            if kind == "snapshot":
                extra = _snapshot_cache_census(cache)
            elif kind == "index":
                extra = _index_file_cache_census(
                    cache,
                    lock=getattr(module, "_artifact_file_index_cache_lock", None),
                )
            else:
                extra = _lru_cache_census(cache)
            rows.append(
                {
                    "name": f"{module_name}.{attr}",
                    "anchor": anchor,
                    "imported": True,
                    "present": True,
                    **extra,
                }
            )
        except Exception:
            rows.append(
                {
                    "name": f"{module_name}.{attr}",
                    "anchor": anchor,
                    "error": True,
                }
            )
    return rows


def _modal_text_input_active(app: Any) -> bool:
    """Return True while a modal screen is accepting text input.

    Only a pushed :class:`~textual.screen.ModalScreen` with a focused
    text input blocks idle collection; chooser-style modals do not.
    Prompt surfaces on the default screen are covered separately by
    ``_prompt_input_active``. Never raises: uncertainty inside a modal
    blocks collection, while an unreadable screen does not.
    """
    try:
        screen = app.screen
    except Exception:
        return False
    try:
        if not isinstance(screen, ModalScreen):
            return False
        focused = screen.focused
    except Exception:
        return True
    try:
        return isinstance(focused, (Input, TextArea))
    except Exception:
        return True


def _classic_thresholds(collector: Any) -> tuple[int, int, int] | None:
    """Return the ``(t0, t1, t2)`` thresholds, or ``None`` elsewhere.

    Only the classic three-generation shape qualifies: a three-tuple of
    non-negative ints. Any other collector shape leaves thresholds alone
    and the idle collector still runs with a time-based due check.
    """
    try:
        raw = tuple(collector.get_threshold())
    except Exception:
        return None
    if len(raw) != 3:
        return None
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in raw):
        return None
    return (int(raw[0]), int(raw[1]), int(raw[2]))


class _NullRecorder:
    """Stand-in recorder when GC telemetry is not installed."""

    def last_full_collection_mono(self) -> float | None:
        return None

    def gen1_since_last_full(self) -> int:
        return 0


def _safe_probe(fn: Callable[[], Any], default: Any) -> Any:
    """Call a UI probe, returning ``default`` if it raises."""
    try:
        return fn()
    except Exception:
        return default


class GCPolicy:
    """One installed idle-GC policy: gate state plus threshold ownership.

    All app access flows through small probe callables so the gate is
    drivable with a fake clock and stubbed collector/recorder. The live
    wiring passes app-bound probes from :func:`install_gc_policy`.
    """

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        last_input_mono: Callable[[], float] | None = None,
        prompt_active: Callable[[], bool] | None = None,
        navigating: Callable[[], bool] | None = None,
        modal_input_active: Callable[[], bool] | None = None,
        loads_done: Callable[[], bool] | None = None,
        collector: Any = gc,
        recorder: Any | None = None,
        trim_runner: Callable[[], None] | None = None,
        census_emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._monotonic = monotonic
        self._last_input_mono = last_input_mono or (lambda: 0.0)
        self._prompt_active = prompt_active or (lambda: False)
        self._navigating = navigating or (lambda: False)
        self._modal_input_active = modal_input_active or (lambda: False)
        self._loads_done = loads_done or (lambda: False)
        self._collector = collector
        if recorder is not None and not (
            hasattr(recorder, "last_full_collection_mono")
            and hasattr(recorder, "gen1_since_last_full")
        ):
            recorder = None
        self._recorder = recorder if recorder is not None else _NullRecorder()
        self._trim_runner = trim_runner or _spawn_trim_thread
        self._census_emit = census_emit
        self._last_census_mono: float | None = None
        self._timer: Any = None
        self.threshold_policy = THRESHOLD_UNSUPPORTED
        self._original_threshold: tuple[int, int, int] | None = None
        self._froze_startup = False
        self._own_last_full_mono: float | None = None
        self._rss_at_last_full: int | None = None
        self._last_full_pause_s: float | None = None
        self._last_trim_mono: float | None = None
        self._logged_survivor_census_skip = False

    def duty_floor_s(self) -> float:
        """Minimum gap after the last full collection (duty-cycle bound).

        The next full collection runs no sooner than ``last_pause *
        DUTY_FACTOR`` after the last one, clamped to ``MAX_DUTY_DELAY_S``
        and floored at ``MIN_FULL_INTERVAL_S``. Unknown pause (no own
        collection yet) degrades to ``MIN_FULL_INTERVAL_S``.
        """
        pause = self._last_full_pause_s
        if pause is None:
            return MIN_FULL_INTERVAL_S
        try:
            pause_f = float(pause)
        except Exception:
            return MIN_FULL_INTERVAL_S
        if pause_f < 0.0:
            pause_f = 0.0
        return max(MIN_FULL_INTERVAL_S, min(pause_f * DUTY_FACTOR, MAX_DUTY_DELAY_S))

    def next_full_due_in_s(self, now_mono: float | None = None) -> float:
        """Seconds until the duty floor lets the next full collection run."""
        now = self._monotonic() if now_mono is None else now_mono
        last_full = self.combined_last_full_mono()
        if last_full is None:
            return 0.0
        try:
            remaining = (float(last_full) + self.duty_floor_s()) - float(now)
        except Exception:
            return 0.0
        return max(0.0, remaining)

    def heartbeat_fields(self) -> dict[str, Any]:
        """Extra heartbeat fields published via ``register_heartbeat_provider``."""
        fields: dict[str, Any] = {"threshold_policy": self.threshold_policy}
        try:
            fields["next_full_due_in_s"] = round(self.next_full_due_in_s(), 3)
            if self._last_full_pause_s is not None:
                fields["last_full_pause_s"] = round(float(self._last_full_pause_s), 6)
        except Exception:
            pass
        return fields

    def apply_thresholds(self) -> str:
        """Raise ``threshold2`` on the classic collector; report the policy."""
        classic = _classic_thresholds(self._collector)
        if classic is None:
            self.threshold_policy = THRESHOLD_UNSUPPORTED
            return self.threshold_policy
        t0, t1, _t2 = classic
        self._original_threshold = classic
        try:
            self._collector.set_threshold(t0, t1, RAISED_THRESHOLD2)
        except Exception:
            self._original_threshold = None
            self.threshold_policy = THRESHOLD_UNSUPPORTED
            return self.threshold_policy
        self.threshold_policy = THRESHOLD_RAISED
        return self.threshold_policy

    def restore_thresholds(self) -> None:
        """Restore the thresholds saved by :meth:`apply_thresholds`."""
        original, self._original_threshold = self._original_threshold, None
        if original is None:
            return
        try:
            self._collector.set_threshold(*original)
        except Exception:
            pass

    def combined_last_full_mono(self) -> float | None:
        """End time of the latest full collection from any trigger."""
        candidates = [self._own_last_full_mono]
        try:
            candidates.append(self._recorder.last_full_collection_mono())
        except Exception:
            pass
        known = [
            value
            for value in candidates
            if isinstance(value, (int, float)) and value >= 0
        ]
        return max(known) if known else None

    def collection_due(self, now_mono: float, last_full_mono: float | None) -> bool:
        """Return True when enough gen-1 work has piled up for a full sweep."""
        try:
            if int(self._recorder.gen1_since_last_full()) >= GEN1_DUE_COUNT:
                return True
        except Exception:
            pass
        classic = _classic_thresholds(self._collector)
        if classic is not None:
            try:
                counts = tuple(self._collector.get_count())
                if int(counts[FULL_GENERATION]) >= GEN1_DUE_COUNT:
                    return True
            except Exception:
                pass
        if last_full_mono is None:
            return True
        return classic is None and now_mono - last_full_mono >= NONCLASSIC_DUE_S

    def idle_gate(self, now_mono: float) -> tuple[bool, str]:
        """Check the idle gate, returning ``(passes, tag)``.

        The tag names the trigger a passing collection would run under:
        ``"idle"``, or a relaxed ``"backstop"`` / ``"rss_backstop"`` once
        the 5-minute or RSS-growth backstop is tripped.
        """
        if not _safe_probe(self._loads_done, False):
            return (False, "idle")
        last_full = self.combined_last_full_mono()
        relaxed = False
        tag = "idle"
        if last_full is not None and now_mono - last_full >= FULL_BACKSTOP_S:
            relaxed = True
            tag = "backstop"
        else:
            rss_now = latest_rss_bytes()
            baseline = self._rss_at_last_full
            if (
                rss_now is not None
                and baseline is not None
                and rss_now - baseline > RSS_GROWTH_BACKSTOP_BYTES
            ):
                relaxed = True
                tag = "rss_backstop"
        quiet = BACKSTOP_QUIET_S if relaxed else IDLE_QUIET_S
        if now_mono - _safe_probe(self._last_input_mono, 0.0) < quiet:
            return (False, tag)
        if _safe_probe(self._prompt_active, False):
            return (False, tag)
        if _safe_probe(self._navigating, False):
            return (False, tag)
        if _safe_probe(self._modal_input_active, False):
            return (False, tag)
        floor = self.duty_floor_s()
        if last_full is not None and now_mono - last_full < floor:
            return (False, tag)
        if not self.collection_due(now_mono, last_full):
            return (False, tag)
        return (True, tag)

    def tick(self, now_mono: float | None = None) -> str | None:
        """Run one 1 s tick; return the collection trigger, if any ran."""
        now = self._monotonic() if now_mono is None else now_mono
        passes, tag = self.idle_gate(now)
        if not passes:
            return None
        if not self._froze_startup:
            start = self._monotonic()
            with gc_trigger("startup_freeze"):
                self._collector.collect()
                self._collector.freeze()
            pause = self._monotonic() - start
            self._froze_startup = True
            self._note_full_collection(pause)
            return "startup_freeze"
        start = self._monotonic()
        if tag == "idle" and self._census_due(now):
            self._run_idle_census(now)
        else:
            with gc_trigger(tag):
                self._collector.collect()
        pause = self._monotonic() - start
        self._note_full_collection(pause)
        self._maybe_trim(now)
        return tag

    def tick_safe(self) -> None:
        """Timer entry point: run :meth:`tick` without ever raising."""
        try:
            self.tick()
        except Exception:
            log.exception("GC policy tick failed")

    def _note_full_collection(self, pause_s: float | None = None) -> None:
        """Record an own full collection and refresh the RSS baseline."""
        self._own_last_full_mono = self._monotonic()
        if pause_s is not None:
            try:
                pause = float(pause_s)
            except Exception:
                pause = None  # type: ignore[assignment]
            if pause is not None:
                if pause < 0.0:
                    pause = 0.0
                self._last_full_pause_s = pause
        try:
            self._rss_at_last_full = latest_rss_bytes()
        except Exception:
            pass

    def _census_due(self, now_mono: float) -> bool:
        """Return True when an idle collection should run the opt-in census."""
        if not _census_enabled():
            return False
        last = self._last_census_mono
        return last is None or now_mono - last >= CENSUS_INTERVAL_S

    def _run_idle_census(self, now_mono: float) -> None:
        """Idle full collection plus garbage/survivor type census.

        Lengthens the pause: ``gc.DEBUG_SAVEALL`` retains collected cycles
        until a second collect frees them. Rate-limited to once per
        ``CENSUS_INTERVAL_S`` and only on the ``idle`` trigger. The
        surviving-types half needs Python 3.14+; earlier interpreters skip
        ``get_objects()`` and emit ``survivor_census:
        "skipped_unsafe_python"``.
        """
        self._last_census_mono = now_mono
        start = self._monotonic()
        collector = self._collector
        previous_debug = 0
        garbage = _TypeCensus(top=[], total=0, watch=[], bytes_total=0)
        get_debug = getattr(collector, "get_debug", None)
        set_debug = getattr(collector, "set_debug", None)
        try:
            if callable(get_debug) and callable(set_debug):
                try:
                    previous_debug = int(get_debug())
                    set_debug(previous_debug | gc.DEBUG_SAVEALL)
                except Exception:
                    set_debug = None
            with gc_trigger("idle"):
                collector.collect()
            garbage = _top_types(tuple(gc.garbage))
            gc.garbage.clear()
        finally:
            if callable(set_debug):
                try:
                    set_debug(previous_debug)
                except Exception:
                    pass
            try:
                with gc_trigger("idle"):
                    collector.collect()
            except Exception:
                pass
        survivor_top: list[dict[str, Any]] = []
        survivor_watch: list[dict[str, Any]] = []
        survivor_count: int | None
        survivor_bytes: int | None
        if _survivor_census_safe():
            survivor_census = "ok"
            survivor_count = 0
            survivor_bytes = 0
            get_objects = getattr(collector, "get_objects", None)
            if callable(get_objects):
                try:
                    survivors = _top_types(get_objects(), watch=CENSUS_WATCHLIST)
                    survivor_top = survivors.top
                    survivor_watch = survivors.watch
                    survivor_count = survivors.total
                    survivor_bytes = survivors.bytes_total
                except Exception:
                    pass
        else:
            survivor_census = "skipped_unsafe_python"
            survivor_count = None
            survivor_bytes = None
            if not self._logged_survivor_census_skip:
                self._logged_survivor_census_skip = True
                log.warning(
                    "Survivor type census skipped: needs Python 3.14+; "
                    "recording collected-garbage types only"
                )
        payload = {
            "garbage_top": garbage.top,
            "survivor_top": survivor_top,
            "survivor_watch": survivor_watch,
            "garbage_count": garbage.total,
            "garbage_bytes": garbage.bytes_total,
            "survivor_count": survivor_count,
            "survivor_bytes": survivor_bytes,
            "survivor_census": survivor_census,
            "known_caches": _known_cache_census(),
            "census_duration_s": round(self._monotonic() - start, 6),
        }
        if self._census_emit is not None:
            self._census_emit({"event": "tui_gc_census", **payload})
        else:
            emit_row("tui_gc_census", payload)

    def _maybe_trim(self, now_mono: float) -> bool:
        """Dispatch an off-thread ``malloc_trim`` at most every 10 minutes."""
        if (
            self._last_trim_mono is not None
            and now_mono - self._last_trim_mono < TRIM_INTERVAL_S
        ):
            return False
        self._last_trim_mono = now_mono
        try:
            self._trim_runner()
        except Exception:
            log.exception("GC policy trim dispatch failed")
        return True


def _trim_allocator_quietly() -> None:
    """Run ``trim_allocator`` off the UI thread; never raise."""
    try:
        trim_allocator()
    except Exception:
        pass


def _spawn_trim_thread() -> None:
    """Wake the persistent daemon worker to run :func:`_trim_allocator_quietly`.

    ``ctypes`` releases the GIL for the foreign ``malloc_trim`` call, so
    the trim does not freeze the UI. The UI tick only sets an Event; it
    never starts a thread.
    """
    _trim_worker_event.set()


def _trim_worker_main() -> None:
    """Wait for allocator-trim requests until the policy is uninstalled."""
    while not _trim_worker_stop.is_set():
        _trim_worker_event.wait()
        _trim_worker_event.clear()
        if _trim_worker_stop.is_set():
            return
        _trim_allocator_quietly()


def _start_trim_worker() -> None:
    """Start the one persistent allocator-trim worker for an installed policy."""
    global _trim_worker
    with _trim_worker_lock:
        if _trim_worker is not None and _trim_worker.is_alive():
            return
        _trim_worker_stop.clear()
        _trim_worker_event.clear()
        worker = threading.Thread(
            target=_trim_worker_main,
            name=TRIM_THREAD_NAME,
            daemon=True,
        )
        _trim_worker = worker
        worker.start()


def _stop_trim_worker() -> None:
    """Wake and join the persistent allocator-trim worker at uninstall."""
    global _trim_worker
    with _trim_worker_lock:
        worker = _trim_worker
        if worker is None:
            return
        _trim_worker_stop.set()
        _trim_worker_event.set()
    if worker is not threading.current_thread():
        worker.join()
    with _trim_worker_lock:
        if _trim_worker is worker:
            _trim_worker = None


def install_gc_policy(
    app: Any = None,
    *,
    tick_interval_s: float = TICK_INTERVAL_S,
    collector: Any = gc,
    recorder: Any | None = None,
    trim_runner: Callable[[], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> GCPolicy | None:
    """Install the idle-GC policy; return the handle or ``None``.

    Raises ``threshold2`` (classic collector only), registers the
    ``threshold_policy`` heartbeat field, and arms the 1 s tick timer.
    Telemetry stays on when the ``SASE_TUI_GC_POLICY_DISABLE=1`` kill
    switch is set: only freeze, threshold, and the idle collector are
    disabled. Safe to call twice: a second install while one is active
    returns the active handle. Never raises: any failure returns
    ``None``.
    """
    global _active
    try:
        if not is_enabled():
            return None
        if _active is not None:
            return _active
        if recorder is None and app is not None:
            recorder = getattr(app, "_gc_telemetry", None)
        nav_gate = getattr(app, "_nav_gate", None) if app is not None else None
        policy = GCPolicy(
            monotonic=monotonic,
            last_input_mono=(
                (lambda: float(getattr(app, "_last_input_mono", 0.0) or 0.0))
                if app is not None
                else None
            ),
            prompt_active=(
                getattr(app, "_prompt_input_active", lambda: False)
                if app is not None
                else None
            ),
            navigating=(
                (lambda: bool(nav_gate.is_navigating()))
                if nav_gate is not None
                else None
            ),
            modal_input_active=(
                (lambda: _modal_text_input_active(app)) if app is not None else None
            ),
            loads_done=(
                (lambda: bool(getattr(app, "_mount_state_loads_done", False)))
                if app is not None
                else None
            ),
            collector=collector,
            recorder=recorder,
            trim_runner=trim_runner,
        )
        policy.apply_thresholds()
        register_heartbeat_provider(HEARTBEAT_PROVIDER_NAME, policy.heartbeat_fields)
        if app is not None and tick_interval_s > 0:
            set_interval = getattr(app, "set_interval", None)
            if callable(set_interval):
                policy._timer = set_interval(
                    tick_interval_s, policy.tick_safe, name=TIMER_NAME
                )
        policy._rss_at_last_full = latest_rss_bytes()
        _start_trim_worker()
        _active = policy
        return policy
    except Exception:
        return None


def uninstall_gc_policy(handle: GCPolicy | None = None) -> None:
    """Stop the tick timer and restore thresholds and freeze state.

    Restores the original thresholds, calls ``gc.unfreeze()`` when this
    policy froze the collector, unregisters the heartbeat provider, and
    stops the timer. Only state this module installed is touched.
    """
    global _active
    target = handle if handle is not None else _active
    if target is None:
        return
    if _active is target:
        _active = None
    _stop_trim_worker()
    timer, target._timer = target._timer, None
    if timer is not None:
        try:
            timer.stop()
        except Exception:
            pass
    try:
        unregister_heartbeat_provider(HEARTBEAT_PROVIDER_NAME)
    except Exception:
        pass
    try:
        target.restore_thresholds()
    except Exception:
        pass
    if target._froze_startup:
        try:
            target._collector.unfreeze()
        except Exception:
            pass
