"""Tests for the config-cache teardown helpers in ``tests._conftest_runtime``.

The autouse isolation fixture drains the config-token refresh worker and
clears the derived ``functools`` caches before monkeypatch restores host
paths. Both helpers run while a test's own patches are still live, so they
must tolerate monkeypatched names and still drain the real caches and the
real worker.
"""

import threading
import time
from unittest.mock import patch

import pytest
from sase.config import core as config_core
from sase.config.core import current_config_token
from tests._config_cache_helpers import _reset_config_token_cache
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests._conftest_runtime import (
    _drain_config_token_refresh,
    _reset_derived_config_caches,
)


def test_reset_derived_caches_tolerates_monkeypatched_cached_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yield teardown must not assume live names still expose cache_clear."""
    monkeypatch.setattr(
        "sase.llm_provider.registry._provider_cli_available",
        lambda _provider: True,
    )
    monkeypatch.setattr(
        "sase.llm_provider.config._get_model_aliases_for_token",
        lambda _token: {},
    )
    monkeypatch.setattr(
        "sase.llm_provider.launch_alias_overrides._parse_env_value",
        lambda _raw: {},
    )
    _reset_derived_config_caches()


def test_reset_derived_caches_clears_originals_while_names_are_patched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Isolation must still drain the real functools caches under a patch."""
    from sase.llm_provider.registry import _provider_cli_available

    original = _provider_cli_available
    original.cache_clear()
    original("claude")
    assert original.cache_info().currsize >= 1

    monkeypatch.setattr(
        "sase.llm_provider.registry._provider_cli_available",
        lambda _provider: True,
    )
    _reset_derived_config_caches()
    assert original.cache_info().currsize == 0


def test_reset_derived_caches_drops_cross_test_session_memos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Memos keyed by one test's homes or session must start cold next test."""
    from collections import OrderedDict

    from sase import _project_display_cache as display_cache
    from sase.ace.tui.actions.agents import _agent_enter_index as enter_index
    from sase.ace.tui.actions.agents import _stranded_toasts
    from sase.ace.tui.widgets.decks import panel_view_deferred
    from sase.footprint import _tui as footprint_tui

    names = {"/tmp/test-home/.sase/projects": object()}
    tokens = {"/tmp/test-home/.sase/projects": ("token",)}
    prebuilt = OrderedDict({("digest", 80, "style"): ((), 1, ())})
    seen = {"demo": frozenset({"sase-demo.1"})}
    counts = {("tui:app.app.focus_next", "key"): 2}
    monkeypatch.setattr(display_cache, "_PROJECT_DISPLAY_NAME_CACHE", names)
    monkeypatch.setattr(display_cache, "_PROJECT_DISPLAY_FRESHNESS_TOKENS", tokens)
    monkeypatch.setattr(panel_view_deferred, "_prebuilt_bodies", prebuilt)
    monkeypatch.setattr(_stranded_toasts, "_SEEN_LEAVES", seen)
    monkeypatch.setattr(enter_index, "_INDEX_CACHE_REF", object())
    monkeypatch.setattr(enter_index, "_INDEX_CACHE", object())
    monkeypatch.setattr(footprint_tui, "_COUNTS", counts)
    generation = display_cache._HUMANIZE_CACHE_GEN

    _reset_derived_config_caches()

    assert names == {}
    assert tokens == {}
    assert display_cache._HUMANIZE_CACHE_GEN == generation + 1
    assert prebuilt == {}
    assert seen == {}
    assert enter_index._INDEX_CACHE_REF is None
    assert enter_index._INDEX_CACHE is None
    assert counts == {}


def test_reset_derived_caches_retires_artifacts_tab_descriptors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later test must neither inherit nor receive an earlier test's tabs.

    The descriptors are served from a process-wide cache that a daemon thread
    refreshes; a refresh still running when its test ends must not publish
    into the next test's cache either.
    """
    from sase.ace.tui import artifact_tabs

    started = threading.Event()
    release = threading.Event()

    def blocked_build() -> tuple[object, ...]:
        started.set()
        assert release.wait(timeout=LOAD_TOLERANT_TIMEOUT)
        return ()

    monkeypatch.setattr(artifact_tabs, "_build_artifacts_subtabs", blocked_build)
    epoch = artifact_tabs._ARTIFACTS_TAB_CACHE_EPOCH
    artifact_tabs._ARTIFACTS_TAB_CACHE = (("earlier-test",), ())
    artifact_tabs._schedule_artifacts_subtabs_refresh(
        ("earlier-test-refresh",), cache_epoch=epoch
    )
    refresher = artifact_tabs._ARTIFACTS_TAB_REFRESH_THREAD
    assert refresher is not None
    assert started.wait(timeout=LOAD_TOLERANT_TIMEOUT)

    try:
        _reset_derived_config_caches()
        assert artifact_tabs._ARTIFACTS_TAB_CACHE is None
        assert artifact_tabs._ARTIFACTS_TAB_CACHE_EPOCH > epoch
    finally:
        release.set()
        refresher.join(timeout=LOAD_TOLERANT_TIMEOUT)
    assert not refresher.is_alive()
    assert artifact_tabs._ARTIFACTS_TAB_CACHE is None


def test_drain_config_token_refresh_joins_worker_and_advances_epoch() -> None:
    """Drain invalidates the generation and waits for the daemon to exit."""
    now = [10.0]
    refresh_started = threading.Event()
    release_refresh = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def compute() -> tuple[str, int]:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 2:
            refresh_started.set()
            assert release_refresh.wait(timeout=2.0)
        return ("token", call_number)

    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
    ):
        _reset_config_token_cache()
        try:
            assert current_config_token() == ("token", 1)
            now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
            assert current_config_token() == ("token", 1)
            assert refresh_started.wait(timeout=1.0)
            epoch_before = config_core._current_config_token_cache_epoch
            worker = config_core._current_config_token_refresh_thread
            assert worker is not None

            def _release() -> None:
                time.sleep(0.02)  # sase-test-wait: lets the drain reach join first
                release_refresh.set()

            threading.Thread(target=_release, daemon=True).start()
            _drain_config_token_refresh()

            assert config_core._current_config_token_cache_epoch > epoch_before
            assert config_core._current_config_token_refresh_thread is None
            assert not worker.is_alive()
            assert current_config_token() == ("token", 3)
        finally:
            release_refresh.set()


def test_drain_timeout_leaves_live_worker_registered() -> None:
    """A timed-out join must not null out a worker that is still running."""
    now = [10.0]
    refresh_started = threading.Event()
    release_refresh = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def compute() -> tuple[str, int]:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 2:
            refresh_started.set()
            assert release_refresh.wait(timeout=2.0)
        return ("token", call_number)

    worker: threading.Thread | None = None
    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
    ):
        try:
            assert current_config_token() == ("token", 1)
            now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
            assert current_config_token() == ("token", 1)
            assert refresh_started.wait(timeout=1.0)
            worker = config_core._current_config_token_refresh_thread
            assert worker is not None

            with pytest.raises(RuntimeError, match="did not exit"):
                _drain_config_token_refresh(timeout=0.05)

            assert config_core._current_config_token_refresh_thread is worker
            assert worker.is_alive()
        finally:
            release_refresh.set()
            if worker is not None:
                worker.join(timeout=2.0)


def test_prior_refresh_worker_cannot_publish_after_drain() -> None:
    """A drained worker cannot install a token into the successor generation."""
    now = [10.0]
    refresh_started = threading.Event()
    release_refresh = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def compute() -> tuple[str, int]:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 2:
            refresh_started.set()
            assert release_refresh.wait(timeout=2.0)
            return ("stale-worker", call_number)
        return ("inline", call_number)

    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
    ):
        _reset_config_token_cache()
        try:
            assert current_config_token() == ("inline", 1)
            now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
            assert current_config_token() == ("inline", 1)
            assert refresh_started.wait(timeout=1.0)

            def _release() -> None:
                time.sleep(0.02)  # sase-test-wait: lets the drain reach join first
                release_refresh.set()

            threading.Thread(target=_release, daemon=True).start()
            _drain_config_token_refresh()
            assert config_core._current_config_token_refresh_thread is None
            assert current_config_token() == ("inline", 3)
            worker = config_core._current_config_token_refresh_thread
            assert worker is not None
            assert worker.is_alive()
            assert current_config_token() == ("inline", 3)
        finally:
            release_refresh.set()
