"""Behavior of the j/k :class:`NavigationGate`."""

from __future__ import annotations

from sase.ace.tui.util.nav_gate import NavigationGate


def test_fresh_gate_reports_idle() -> None:
    gate = NavigationGate(window_s=0.25)
    assert not gate.is_navigating(now_mono=1000.0)
    assert gate.time_until_idle(now_mono=1000.0) == 0.0


def test_record_within_window_is_navigating() -> None:
    gate = NavigationGate(window_s=0.25)
    gate.record(now_mono=1000.0)
    # 100 ms after record — well inside the 250 ms window.
    assert gate.is_navigating(now_mono=1000.10)
    assert 0.14 < gate.time_until_idle(now_mono=1000.10) < 0.16


def test_record_past_window_is_idle() -> None:
    gate = NavigationGate(window_s=0.25)
    gate.record(now_mono=1000.0)
    # 300 ms after record — outside the window.
    assert not gate.is_navigating(now_mono=1000.30)
    assert gate.time_until_idle(now_mono=1000.30) == 0.0


def test_repeated_record_extends_window() -> None:
    """Holding j/k continuously keeps the gate active across the burst."""
    gate = NavigationGate(window_s=0.25)
    gate.record(now_mono=1000.0)
    gate.record(now_mono=1000.20)
    # 1000.30 is past first record's window but within second's.
    assert gate.is_navigating(now_mono=1000.30)


def test_window_boundary_is_exclusive() -> None:
    """Exactly at the window boundary the user counts as idle."""
    gate = NavigationGate(window_s=0.25)
    gate.record(now_mono=1000.0)
    assert not gate.is_navigating(now_mono=1000.25)


def test_negative_window_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        NavigationGate(window_s=-0.1)
