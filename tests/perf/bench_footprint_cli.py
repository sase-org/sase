"""Steady-state benchmark for the per-process Footprint CLI recorder.

Run with ``pytest -s -m slow tests/perf/bench_footprint_cli.py``. The budget
covers mode and actor classification, ID/option shaping, and one append; module
imports are warmed before the timed samples.
"""

from __future__ import annotations

import math
from pathlib import Path
import time

import pytest

from sase.footprint._cli import begin

pytestmark = pytest.mark.slow


def test_cli_recording_p99_is_under_100_microseconds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setenv("SASE_FOOTPRINT", "local")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)

    for _ in range(30):
        hit = begin()
        hit.set_path(("footprint", "catalog"))
        hit.set_options(("area", "format"))
        hit.record(0)

    samples: list[int] = []
    for _ in range(600):
        started = time.perf_counter_ns()
        hit = begin()
        hit.set_path(("footprint", "catalog"))
        hit.set_options(("area", "format"))
        hit.record(0)
        samples.append(time.perf_counter_ns() - started)

    ordered = sorted(samples)
    p99_ns = ordered[math.ceil(0.99 * len(ordered)) - 1]
    p99_us = p99_ns / 1_000
    print(f"Footprint CLI recorder steady-state p99: {p99_us:.2f} µs")
    assert p99_ns <= 100_000
