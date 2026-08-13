"""Tests for :mod:`sase.monitor.identity`."""

from __future__ import annotations

import os

import pytest

from sase.monitor.identity import process_identity, supervisor_is_alive

from ._fixtures import DEAD_PID


def test_process_identity_is_stable_for_the_current_process() -> None:
    first = process_identity(os.getpid())
    second = process_identity(os.getpid())

    assert first == second


def test_supervisor_is_alive_is_false_for_a_dead_pid() -> None:
    assert supervisor_is_alive(DEAD_PID, None) is False


def test_supervisor_is_alive_is_false_for_a_none_pid() -> None:
    assert supervisor_is_alive(None, "whatever") is False


def test_supervisor_is_alive_is_true_with_no_recorded_identity() -> None:
    assert supervisor_is_alive(os.getpid(), None) is True


def test_supervisor_is_alive_is_true_when_identity_matches() -> None:
    identity = process_identity(os.getpid())

    assert supervisor_is_alive(os.getpid(), identity) is True


def test_supervisor_is_alive_is_false_when_the_pid_has_been_recycled() -> None:
    current = process_identity(os.getpid())
    if not current:
        pytest.skip("no /proc process identity support on this platform")

    assert supervisor_is_alive(os.getpid(), "recycled-boot-id:0") is False
