"""Regression tests for deterministic visual-snapshot startup patches.

sase-14q: ACE PNG goldens drifted on hosts with provider CLIs because the
visual harness let a real ``usage-refresh`` proc start and stay running at
capture time, rendering a top-bar gear chip the committed goldens lack.
``patch_startup_loaders`` must pin both the usage-refresh fallback and the
live proc observer off so captures are host-independent.
"""

from __future__ import annotations

import pytest

from sase.ace.tui.actions._usage_refresh_fallback import UsageRefreshFallbackMixin
from sase.ace.tui.proc_observer import ProcObserver
from tests.ace.tui.visual._ace_png_snapshot_startup import patch_startup_loaders


def test_patch_startup_loaders_neutralizes_usage_refresh_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The usage-refresh fallback must schedule nothing in visual captures."""
    original = UsageRefreshFallbackMixin._schedule_usage_refresh_fallback
    patch_startup_loaders(monkeypatch)
    patched = UsageRefreshFallbackMixin._schedule_usage_refresh_fallback
    assert patched is not original
    assert patched(object()) is None


def test_patch_startup_loaders_covers_ace_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """AceApp must resolve the fallback through the neutralized mixin."""
    from sase.ace.tui import AceApp

    patch_startup_loaders(monkeypatch)
    assert (
        AceApp._schedule_usage_refresh_fallback
        is UsageRefreshFallbackMixin._schedule_usage_refresh_fallback
    )


def test_patch_startup_loaders_stops_live_proc_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live proc observer must not start reading host store state."""
    original = ProcObserver.start
    patch_startup_loaders(monkeypatch)
    assert ProcObserver.start is not original
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.start()
    assert not observer.running
