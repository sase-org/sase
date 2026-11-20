"""Test gc telemetry lifecycle tests."""

from __future__ import annotations

import gc

import pytest

from sase.ace.tui.util import _gc_telemetry_lifecycle as lifecycle_module
from sase.ace.tui.util import gc_telemetry
from sase.ace.tui.util.gc_telemetry import (
    install_gc_telemetry,
    latest_rss_bytes,
    uninstall_gc_telemetry,
)


def test_install_uninstall_restores_gc_callbacks() -> None:
    assert lifecycle_module._active is None
    before = list(gc.callbacks)
    assert lifecycle_module._gc_callback not in before
    handle = install_gc_telemetry()
    try:
        assert handle is not None
        assert lifecycle_module._active is handle
        assert lifecycle_module._gc_callback in gc.callbacks
        assert install_gc_telemetry() is handle
        thread = handle._thread
        assert thread is not None
        assert thread.name == gc_telemetry.THREAD_NAME
        assert thread.daemon is True
    finally:
        uninstall_gc_telemetry(handle)
    assert list(gc.callbacks) == before
    assert lifecycle_module._active is None


def test_install_respects_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(gc_telemetry.ENV_DISABLE, "1")
    before = list(gc.callbacks)
    assert install_gc_telemetry() is None
    assert list(gc.callbacks) == before
    assert lifecycle_module._active is None


def test_latest_rss_bytes_without_active() -> None:
    previous = lifecycle_module._active
    lifecycle_module._active = None
    try:
        assert latest_rss_bytes() is None
    finally:
        lifecycle_module._active = previous
