"""Tests for :mod:`sase.monitor.naming`."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.monitor.naming import (
    _MONITOR_ID_ALPHABET,
    _MONITOR_ID_LENGTH,
    SHORT_MONITOR_ID_LENGTH,
    allocate_monitor_suffix,
    new_monitor_id,
    short_monitor_id,
)


def test_first_monitor_in_a_lane_takes_the_plain_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    assert allocate_monitor_suffix("acme", has_existing_monitor=False) == "--mon"


def test_later_monitors_allocate_a_sequence_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    assert allocate_monitor_suffix("acme", has_existing_monitor=True) == "--mon-0"


def test_new_monitor_id_is_unique_lowercase_and_matches_task_id_shape() -> None:
    ids = {new_monitor_id() for _ in range(50)}
    assert len(ids) == 50
    for monitor_id in ids:
        assert len(monitor_id) == _MONITOR_ID_LENGTH
        assert all(char in _MONITOR_ID_ALPHABET for char in monitor_id)


def test_short_monitor_id_truncates_to_the_display_prefix() -> None:
    monitor_id = new_monitor_id()

    assert short_monitor_id(monitor_id) == monitor_id[:SHORT_MONITOR_ID_LENGTH]
    assert len(short_monitor_id(monitor_id)) == SHORT_MONITOR_ID_LENGTH
