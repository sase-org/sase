"""Tests for the session-scoped registered-error pointer."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator

import pytest

from sase.logs.error_registry import (
    clear_registered_errors,
    error_anchor,
    last_registered_error,
    new_error_id,
    register_error,
)

_ERROR_ID_RE = r"^err_\d{6}_\d{6}_[0-9a-f]{6}$"


@pytest.fixture(autouse=True)
def _clear_registered_errors() -> Iterator[None]:
    clear_registered_errors()
    yield
    clear_registered_errors()


def test_new_error_id_shape_and_uniqueness() -> None:
    ids = [new_error_id() for _ in range(8)]
    assert all(re.fullmatch(_ERROR_ID_RE, item) for item in ids)
    assert len(set(ids)) == len(ids)


def test_error_anchor_round_trip() -> None:
    error_id = "err_260617_143000_7f3a9c"
    assert error_anchor(error_id) == f"[{error_id}]"
    record = register_error(
        error_id=error_id,
        source_id="launch_failures",
        summary="Launch failed",
    )
    assert record.anchor == error_anchor(error_id)
    assert record.error_id == error_id
    assert record.source_id == "launch_failures"
    assert record.summary == "Launch failed"
    assert record.registered_at


def test_last_write_wins() -> None:
    first = register_error(
        error_id="err_260617_143000_aaaaaa",
        source_id="launch_failures",
        summary="first",
    )
    second = register_error(
        error_id="err_260617_143001_bbbbbb",
        source_id="tui",
        summary="second",
    )
    assert last_registered_error() == second
    assert last_registered_error() != first


def test_clear_registered_errors() -> None:
    register_error(
        error_id="err_260617_143000_cccccc",
        source_id="launch_failures",
        summary="gone",
    )
    clear_registered_errors()
    assert last_registered_error() is None


def test_register_error_is_thread_safe() -> None:
    worker_count = 32
    barrier = threading.Barrier(worker_count)
    summaries = [f"worker-{index}" for index in range(worker_count)]

    def worker(index: int) -> None:
        barrier.wait()
        register_error(
            error_id=f"err_260617_143000_{index:06x}",
            source_id="launch_failures",
            summary=summaries[index],
        )

    threads = [
        threading.Thread(target=worker, args=(index,)) for index in range(worker_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    last = last_registered_error()
    assert last is not None
    assert last.source_id == "launch_failures"
    assert last.summary in summaries
    assert last.anchor == error_anchor(last.error_id)
