"""Tests for the config freshness token and its background refresh worker.

``current_config_token`` serves an expired token immediately and recomputes
it off-thread, so these tests drive a fake clock and gate the recompute on
events to pin the stale-while-revalidate, single-flight, and explicit
invalidation behavior. See ``test_config_cache_teardown.py`` for the
isolation fixture's drain of that same worker.
"""

import threading
import time
from unittest.mock import patch

from sase.config import core as config_core
from sase.config.core import clear_config_cache, current_config_token
from tests._config_cache_helpers import (
    _reset_config_token_cache,
    _wait_for_config_token,
)


def test_current_config_token_serves_stale_while_refreshing() -> None:
    """An expired token returns immediately while freshness I/O runs off-thread."""
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
            first = current_config_token()
            now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS / 2
            assert current_config_token() is first
            assert calls == 1

            now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS
            assert current_config_token() is first
            assert refresh_started.wait(timeout=1.0)
            assert current_config_token() is first
            assert calls == 2

            release_refresh.set()
            _wait_for_config_token(("token", 2))
        finally:
            release_refresh.set()


def test_current_config_token_refresh_is_single_flight() -> None:
    """Concurrent expired reads coalesce behind one daemon recompute."""
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
            first = current_config_token()
            now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
            assert current_config_token() is first
            assert refresh_started.wait(timeout=1.0)

            results: list[tuple] = []
            readers = [
                threading.Thread(target=lambda: results.append(current_config_token()))
                for _ in range(12)
            ]
            for reader in readers:
                reader.start()
            for reader in readers:
                reader.join(timeout=1.0)

            assert len(results) == len(readers)
            assert all(token is first for token in results)
            assert calls == 2

            release_refresh.set()
            _wait_for_config_token(("token", 2))
        finally:
            release_refresh.set()


def test_first_config_token_read_does_not_start_worker() -> None:
    """A one-shot CLI lookup computes inline without creating a thread."""
    with patch(
        "sase.config.core._compute_current_config_token",
        return_value=("token", 1),
    ):
        _reset_config_token_cache()
        assert current_config_token() == ("token", 1)

    assert config_core._current_config_token_refresh_thread is None


def test_clear_config_cache_resets_config_token_time_gate() -> None:
    """An explicit clear forces immediate token recomputation within the window."""
    with patch(
        "sase.config.core._compute_current_config_token",
        side_effect=[("token", 1), ("token", 2)],
    ) as compute:
        _reset_config_token_cache()
        assert current_config_token() == ("token", 1)
        clear_config_cache()
        assert current_config_token() == ("token", 2)

    assert compute.call_count == 2


def test_explicit_invalidation_wins_race_with_background_refresh() -> None:
    """A stale worker cannot overwrite an inline post-clear token swap."""
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

            clear_config_cache()
            assert current_config_token() == ("token", 3)

            release_refresh.set()
            deadline = time.perf_counter() + 2.0
            while config_core._current_config_token_refresh_thread is not None:
                assert time.perf_counter() < deadline
                time.sleep(min(0.01, max(0.0, deadline - time.perf_counter())))
            assert current_config_token() == ("token", 3)
        finally:
            release_refresh.set()
