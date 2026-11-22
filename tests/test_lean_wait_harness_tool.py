"""Smoke test for ``tools/lean_wait_harness``, the parked-waiter RSS/CPU harness."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._lean_wait_helpers import WAITER_PATH

HARNESS = Path(__file__).resolve().parents[1] / "tools" / "lean_wait_harness"

pytestmark = pytest.mark.skipif(
    not Path("/proc/self/status").exists(), reason="the harness samples /proc"
)


def _run_harness(tmp_path: Path, *args: str) -> dict[str, object]:
    out = tmp_path / "harness.json"
    completed = subprocess.run(
        [sys.executable, str(HARNESS), "--json", str(out), *args],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    report: dict[str, object] = json.loads(out.read_text(encoding="utf-8"))
    assert report == json.loads(completed.stdout)
    return report


def test_harness_is_pointed_at_the_real_waiter() -> None:
    assert WAITER_PATH.name == "run_agent_lean_wait.py"
    assert "run_agent_lean_wait.py" in HARNESS.read_text(encoding="utf-8")


def test_harness_reports_rss_cpu_probes_and_release_latency(tmp_path: Path) -> None:
    report = _run_harness(
        tmp_path,
        "--heartbeat",
        "stale",
        "--minutes",
        "0.12",
        "--sample-seconds",
        "1",
        "--probe-interval",
        "1",
        "--end-action",
        "release",
    )

    assert report["heartbeat"] == "stale"
    (waiter,) = report["waiters"]  # type: ignore[misc]
    assert waiter["probes_observed"] >= 1
    assert 0 < waiter["vmrss_kb"]["median"] < 40 * 1024
    assert waiter["rss_anon_kb"]["median"] > 0
    assert waiter["cpu_pct_total"] >= waiter["cpu_pct_own"] >= 0
    (latency,) = report["release_latency_s"]  # type: ignore[misc]
    assert 0 <= latency < 5


def test_harness_times_the_kill_path(tmp_path: Path) -> None:
    report = _run_harness(
        tmp_path,
        "--heartbeat",
        "fresh",
        "--minutes",
        "0.05",
        "--sample-seconds",
        "1",
        "--end-action",
        "term",
    )

    (waiter,) = report["waiters"]  # type: ignore[misc]
    # A fresh heartbeat with the default 1,800 s safety interval never probes.
    assert waiter["probes_observed"] == 0
    (latency,) = report["kill_latency_s"]  # type: ignore[misc]
    assert 0 <= latency < 5
