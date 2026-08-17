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
            assert current_config_token() == ("inline", 3)
            deadline = time.perf_counter() + 2.0
            while config_core._current_config_token_refresh_thread is not None:
                assert time.perf_counter() < deadline
                time.sleep(min(0.01, max(0.0, deadline - time.perf_counter())))
            assert current_config_token() == ("inline", 3)
        finally:
            release_refresh.set()
