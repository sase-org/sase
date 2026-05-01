"""Tests for axe maintenance marker helpers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.maintenance import (
    MAINTENANCE_FILENAME,
    clear_maintenance,
    clear_stale_maintenance,
    enter_maintenance,
    read_maintenance,
    start_maintenance,
)
from sase.core.time import get_timezone


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    state_dir = tmp_path / ".sase" / "axe"
    with patch("sase.axe.state.AXE_STATE_DIR", state_dir):
        yield state_dir


def test_start_read_and_clear_maintenance(temp_state_dir: Path) -> None:
    marker = start_maintenance("install_sase_github")

    assert marker["reason"] == "install_sase_github"
    assert read_maintenance() == marker

    assert clear_maintenance() is True
    assert read_maintenance() is None
    assert clear_maintenance() is False


def test_clear_stale_maintenance_removes_old_marker(temp_state_dir: Path) -> None:
    old_started_at = datetime.now(get_timezone()) - timedelta(hours=25)
    temp_state_dir.mkdir(parents=True)
    marker_path = temp_state_dir / MAINTENANCE_FILENAME
    old_marker = {
        "reason": "old_install",
        "pid": 123,
        "started_at": old_started_at.isoformat(),
    }
    marker_path.write_text(json.dumps(old_marker))

    cleared = clear_stale_maintenance(max_age_seconds=60)

    assert cleared == old_marker
    assert read_maintenance() is None
    assert not marker_path.exists()


def test_clear_stale_maintenance_preserves_recent_marker(temp_state_dir: Path) -> None:
    marker = start_maintenance("recent_install")

    assert clear_stale_maintenance(max_age_seconds=60) is None
    assert read_maintenance() == marker


def test_clear_stale_maintenance_removes_recent_dead_pid_marker(
    temp_state_dir: Path,
) -> None:
    marker = start_maintenance("dead_install")

    with patch("sase.axe.maintenance.is_process_running", return_value=False):
        cleared = clear_stale_maintenance(max_age_seconds=60)

    assert cleared == marker
    assert read_maintenance() is None
    assert not (temp_state_dir / MAINTENANCE_FILENAME).exists()


def test_clear_stale_maintenance_preserves_recent_live_pid_marker(
    temp_state_dir: Path,
) -> None:
    marker = start_maintenance("live_install")

    with patch("sase.axe.maintenance.is_process_running", return_value=True):
        assert clear_stale_maintenance(max_age_seconds=60) is None

    assert read_maintenance() == marker


def test_clear_stale_maintenance_removes_malformed_timestamp(
    temp_state_dir: Path,
) -> None:
    temp_state_dir.mkdir(parents=True)
    marker_path = temp_state_dir / MAINTENANCE_FILENAME
    malformed_marker = {
        "reason": "bad_timestamp",
        "pid": 123,
        "started_at": "not-a-timestamp",
    }
    marker_path.write_text(json.dumps(malformed_marker))

    cleared = clear_stale_maintenance(max_age_seconds=60)

    assert cleared == malformed_marker
    assert read_maintenance() is None
    assert not marker_path.exists()


def test_enter_maintenance_clears_marker_on_exit(temp_state_dir: Path) -> None:
    with enter_maintenance("test"):
        assert read_maintenance() is not None

    assert read_maintenance() is None
