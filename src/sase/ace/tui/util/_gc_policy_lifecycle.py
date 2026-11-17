"""Install/uninstall wiring for the idle-time full-GC policy."""

from __future__ import annotations

import gc
import time
from collections.abc import Callable
from typing import Any

from textual.screen import ModalScreen
from textual.widgets import Input, TextArea

from sase.ace.tui.util.gc_telemetry import (
    latest_rss_bytes,
    register_heartbeat_provider,
    unregister_heartbeat_provider,
)

from ._gc_policy_config import (
    HEARTBEAT_PROVIDER_NAME,
    TICK_INTERVAL_S,
    TIMER_NAME,
    is_enabled,
)
from ._gc_policy_policy import GCPolicy
from ._gc_policy_trim import start_trim_worker, stop_trim_worker

_active: GCPolicy | None = None


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
        start_trim_worker()
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
    stop_trim_worker()
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
