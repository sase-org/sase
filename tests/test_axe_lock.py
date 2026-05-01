"""Tests for axe lifecycle locking."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.lock import AxeLifecycleLock


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    state_dir = tmp_path / ".sase" / "axe"
    state_dir.mkdir(parents=True, exist_ok=True)
    with patch("sase.axe.state.AXE_STATE_DIR", state_dir):
        yield state_dir


def test_lifecycle_lock_is_exclusive(temp_state_dir: Path) -> None:
    first = AxeLifecycleLock.acquire(blocking=False)
    assert first is not None
    try:
        assert AxeLifecycleLock.acquire(blocking=False) is None
    finally:
        first.release()

    second = AxeLifecycleLock.acquire(blocking=False)
    assert second is not None
    second.release()


def test_stale_lock_file_does_not_block_acquisition(temp_state_dir: Path) -> None:
    path = temp_state_dir / "orchestrator.lock"
    path.write_text("stale")

    lock = AxeLifecycleLock.acquire(blocking=False)
    assert lock is not None
    lock.release()
