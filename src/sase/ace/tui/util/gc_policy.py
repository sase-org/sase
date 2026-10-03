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
- freed arenas returned with ``malloc_trim`` on a worker thread.

Every collection runs under :func:`gc_trigger` (from
:mod:`sase.ace.tui.util.gc_telemetry`) so ``tui_gc_pause`` rows carry the
``startup_freeze`` / ``idle`` / ``backstop`` / ``rss_backstop`` trigger and the
watchdog can attribute any resulting hitch. The policy is driven by a 1 s
``set_interval`` whose callback stays thin and synchronous; it never reads
``/proc`` on the UI thread (RSS comes from the telemetry heartbeat sample)
and never auto-installs under the ``sase.ace.testing`` harness.
"""

from __future__ import annotations

import gc
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from textual.screen import ModalScreen
from textual.widgets import Input, TextArea

from sase.ace.tui.util.gc_telemetry import (
    gc_trigger,
    latest_rss_bytes,
    register_heartbeat_provider,
    unregister_heartbeat_provider,
)
from sase.axe.runner_idle_memory import trim_allocator

log = logging.getLogger(__name__)

ENV_DISABLE = "SASE_TUI_GC_POLICY_DISABLE"
TICK_INTERVAL_S = 1.0
IDLE_QUIET_S = 3.0
BACKSTOP_QUIET_S = 1.0
MIN_FULL_INTERVAL_S = 60.0
FULL_BACKSTOP_S = 5 * 60.0
RSS_GROWTH_BACKSTOP_BYTES = 500 * 1024 * 1024
GEN1_DUE_COUNT = 100
NONCLASSIC_DUE_S = 120.0
RAISED_THRESHOLD2 = 10_000
TRIM_INTERVAL_S = 10 * 60.0
TIMER_NAME = "gc-policy"
TRIM_THREAD_NAME = "sase-tui-gc-trim"
HEARTBEAT_PROVIDER_NAME = "gc_policy"
THRESHOLD_RAISED = "raised"
THRESHOLD_UNSUPPORTED = "unsupported"
FULL_GENERATION = 2

_active: GCPolicy | None = None


def is_enabled() -> bool:
    """Return whether the GC policy may install (kill switch aware)."""
    return os.environ.get(ENV_DISABLE) != "1"


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
        self._timer: Any = None
        self.threshold_policy = THRESHOLD_UNSUPPORTED
        self._original_threshold: tuple[int, int, int] | None = None
        self._froze_startup = False
        self._own_last_full_mono: float | None = None
        self._rss_at_last_full: int | None = None
        self._last_trim_mono: float | None = None

    def heartbeat_fields(self) -> dict[str, Any]:
        """Extra heartbeat fields published via ``register_heartbeat_provider``."""
        return {"threshold_policy": self.threshold_policy}

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
        if last_full is not None and now_mono - last_full < MIN_FULL_INTERVAL_S:
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
            with gc_trigger("startup_freeze"):
                self._collector.collect()
                self._collector.freeze()
            self._froze_startup = True
            self._note_full_collection()
            return "startup_freeze"
        with gc_trigger(tag):
            self._collector.collect()
        self._note_full_collection()
        self._maybe_trim(now)
        return tag

    def tick_safe(self) -> None:
        """Timer entry point: run :meth:`tick` without ever raising."""
        try:
            self.tick()
        except Exception:
            log.exception("GC policy tick failed")

    def _note_full_collection(self) -> None:
        """Record an own full collection and refresh the RSS baseline."""
        self._own_last_full_mono = self._monotonic()
        try:
            self._rss_at_last_full = latest_rss_bytes()
        except Exception:
            pass

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
    """Dispatch :func:`_trim_allocator_quietly` on a daemon worker thread.

    ``ctypes`` releases the GIL for the foreign ``malloc_trim`` call, so
    the trim does not freeze the UI.
    """
    thread = threading.Thread(
        target=_trim_allocator_quietly,
        name=TRIM_THREAD_NAME,
        daemon=True,
    )
    thread.start()


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
