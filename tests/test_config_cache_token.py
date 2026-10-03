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
from tests._conftest_runtime import _drain_config_token_refresh


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


def test_config_token_interval_exceeds_tui_tick_cadence() -> None:
    """One-second TUI ticks should not force config revalidation every tick."""
    now = [10.0]

    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch(
            "sase.config.core._compute_current_config_token",
            return_value=("token", 1),
        ) as compute,
    ):
        _reset_config_token_cache()
        assert config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS > 1.0
        first = current_config_token()
        worker = config_core._current_config_token_refresh_thread
        assert worker is not None

        for _ in range(4):
            now[0] += 1.0
            assert current_config_token() is first

        assert compute.call_count == 1
        assert config_core._current_config_token_refresh_thread is worker


def test_config_token_refresh_thread_starts_after_lock_release() -> None:
    """Thread bootstrap must not run while the config-token cache lock is held."""
    now = [10.0]
    calls = 0
    refresh_started = threading.Event()
    release_refresh = threading.Event()
    start_lock_states: list[bool] = []

    real_thread = threading.Thread

    class ObservedThread(real_thread):
        def start(self) -> None:
            start_lock_states.append(
                config_core._current_config_token_cache_lock._is_owned()
            )
            super().start()

    def compute() -> tuple[str, int]:
        nonlocal calls
        calls += 1
        if calls == 2:
            refresh_started.set()
            assert release_refresh.wait(timeout=2.0)
        return ("token", calls)

    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
        patch("sase.config.core.threading.Thread", ObservedThread),
    ):
        _reset_config_token_cache()
        try:
            first = current_config_token()
            # The long-lived revalidator starts once at warm-up, outside the lock.
            assert start_lock_states == [False]
            worker = config_core._current_config_token_refresh_thread
            assert worker is not None
            now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
            assert current_config_token() is first
            assert refresh_started.wait(timeout=1.0)

            # Expiry wakes the same worker; no additional Thread.start occurs.
            assert config_core._current_config_token_refresh_thread is worker
            assert start_lock_states == [False]
            release_refresh.set()
            _wait_for_config_token(("token", 2))
            assert worker.is_alive()
            assert config_core._current_config_token_refresh_thread is worker
        finally:
            release_refresh.set()

    assert start_lock_states == [False]


def test_first_config_token_read_starts_long_lived_revalidator() -> None:
    """Warm-up computes inline once and starts one long-lived revalidator."""
    with patch(
        "sase.config.core._compute_current_config_token",
        return_value=("token", 1),
    ):
        _reset_config_token_cache()
        assert current_config_token() == ("token", 1)

    worker = config_core._current_config_token_refresh_thread
    assert worker is not None
    assert worker.is_alive()
    assert worker.name == config_core.CONFIG_TOKEN_REFRESH_THREAD_NAME


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


def test_refresh_worker_only_deregisters_itself() -> None:
    """A stale recompute must not overwrite a newer generation.

    The long-lived revalidator publishes only when its captured epoch still
    matches, so a recompute that missed its drain window cannot install a
    stale token into the successor generation, and publishing never clears
    the live worker registration.
    """
    now = [10.0]

    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch(
            "sase.config.core._compute_current_config_token",
            return_value=("inline", 1),
        ),
    ):
        _reset_config_token_cache()
        first = current_config_token()
        worker = config_core._current_config_token_refresh_thread
        assert worker is not None
        epoch = config_core._current_config_token_cache_epoch
        cwd = config_core._current_config_token_cache_cwd

        # Simulate a drain advancing the generation: a stale recompute
        # captured before the bump must decline to publish.
        with config_core._current_config_token_cache_lock:
            config_core._current_config_token_cache_epoch += 1
        config_core._publish_revalidator_token(
            ("stale", 99), cache_epoch=epoch, cache_cwd=cwd
        )
        assert config_core._current_config_token_cache_value is first
        assert config_core._current_config_token_refresh_thread is worker
        assert worker.is_alive()


def test_current_config_token_recomputes_after_chdir(tmp_path, monkeypatch) -> None:
    """A ``chdir`` invalidates the cached token even inside the refresh window."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    now = [10.0]
    calls = 0

    def compute() -> tuple[str, int]:
        nonlocal calls
        calls += 1
        return ("token", calls)

    monkeypatch.chdir(dir_a)
    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
    ):
        _reset_config_token_cache()
        first = current_config_token()

        monkeypatch.chdir(dir_b)
        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS / 2
        second = current_config_token()

    assert second != first
    assert calls == 2


def test_config_token_refresh_worker_declines_to_publish_after_chdir(
    tmp_path, monkeypatch
) -> None:
    """A background refresh that raced a ``chdir`` must not publish its token."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

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

    monkeypatch.chdir(dir_a)
    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
    ):
        _reset_config_token_cache()
        try:
            first = current_config_token()
            worker = config_core._current_config_token_refresh_thread
            assert worker is not None
            now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
            assert current_config_token() is first
            assert refresh_started.wait(timeout=1.0)

            # chdir while the revalidator is blocked mid-compute for dir_a.
            monkeypatch.chdir(dir_b)
            release_refresh.set()
            time.sleep(  # sase-test-wait: let revalidator decline publish
                0.2
            )
            assert worker.is_alive()

            # The revalidator computed a token for dir_a; it must not publish
            # over a cache now keyed to dir_b. The long-lived revalidator
            # may retry (declining each time) until the synchronous read
            # below rekeys the cache, so only bound the call count from below.
            assert config_core._current_config_token_cache_value == first
            assert config_core._current_config_token_refresh_thread is worker

            third = current_config_token()
            assert third != first
            assert calls >= 3
        finally:
            release_refresh.set()


def test_explicit_invalidation_wins_race_with_background_refresh() -> None:
    """A stale recompute cannot overwrite an inline post-clear token swap."""
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
            worker = config_core._current_config_token_refresh_thread
            assert worker is not None
            now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
            assert current_config_token() == ("token", 1)
            assert refresh_started.wait(timeout=1.0)

            clear_config_cache()
            assert current_config_token() == ("token", 3)

            release_refresh.set()
            # The stale recompute declines (epoch moved); the live
            # revalidator stays registered with the post-clear token.
            deadline = time.perf_counter() + 2.0
            while config_core._current_config_token_cache_value != ("token", 3):
                assert time.perf_counter() < deadline
                time.sleep(min(0.01, max(0.0, deadline - time.perf_counter())))
            time.sleep(  # sase-test-wait: settle stale-recompute window
                0.1
            )
            assert config_core._current_config_token_cache_value == ("token", 3)
            assert config_core._current_config_token_refresh_thread is worker
            assert worker.is_alive()
            assert current_config_token() == ("token", 3)
        finally:
            release_refresh.set()


def test_getter_never_starts_thread_after_warmup() -> None:
    """Expired reads peek; the long-lived revalidator does the refresh."""
    now = [10.0]
    real_thread = threading.Thread
    starts: list[bool] = []

    class CountingThread(real_thread):
        def start(self) -> None:
            starts.append(True)
            super().start()

    def compute() -> tuple[str, int]:
        return ("token", int(now[0]))

    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
        patch("sase.config.core.threading.Thread", CountingThread),
    ):
        _reset_config_token_cache()
        first = current_config_token()
        assert len(starts) == 1
        worker = config_core._current_config_token_refresh_thread
        assert worker is not None

        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
        for _ in range(5):
            assert current_config_token() is first
        assert len(starts) == 1
        assert config_core._current_config_token_refresh_thread is worker

        _wait_for_config_token(("token", int(now[0])))
        assert len(starts) == 1
        assert config_core._current_config_token_refresh_thread is worker


def test_revalidator_picks_up_changed_config_within_one_cadence() -> None:
    """A changed config publishes via the running revalidator, not a new thread."""
    now = [10.0]
    calls = 0

    def compute() -> tuple[str, int]:
        nonlocal calls
        calls += 1
        return ("token", calls)

    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
    ):
        _reset_config_token_cache()
        first = current_config_token()
        worker = config_core._current_config_token_refresh_thread
        assert worker is not None
        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
        assert current_config_token() is first
        _wait_for_config_token(("token", 2))
        assert calls == 2
        assert config_core._current_config_token_refresh_thread is worker
        assert worker.is_alive()

        clear_config_cache()
        assert current_config_token() == ("token", 3)
        assert calls == 3


def _barrier_reader(barrier: threading.Barrier, failures: list[BaseException]) -> None:
    try:
        barrier.wait(timeout=2.0)
        current_config_token()
    except BaseException as exc:  # noqa: BLE001 - collected for assert
        failures.append(exc)


def test_concurrent_first_reads_start_single_revalidator() -> None:
    """Concurrent first reads behind a barrier start exactly one revalidator."""
    for _ in range(25):
        _drain_config_token_refresh()
        barrier = threading.Barrier(8)
        failures: list[BaseException] = []

        readers = [
            threading.Thread(target=_barrier_reader, args=(barrier, failures))
            for _ in range(8)
        ]
        for reader in readers:
            reader.start()
        for reader in readers:
            reader.join(timeout=5.0)
        assert not failures
        assert all(not reader.is_alive() for reader in readers)

        workers = [
            thread
            for thread in threading.enumerate()
            if thread.name == config_core.CONFIG_TOKEN_REFRESH_THREAD_NAME
            and thread.is_alive()
        ]
        assert len(workers) == 1
        assert config_core._current_config_token_refresh_thread is workers[0]
