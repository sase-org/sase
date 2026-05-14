"""Benchmark direct vs daemon-backed ACE startup read slices.

Run directly when investigating ACE daemon read-through latency::

    python -m tests.perf.bench_ace_daemon_reads --runs 3

The report is intentionally JSON-first so it can be attached to rollout
diagnostics or compared across daemon healthy/unhealthy runs.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._notification_provider import (
    read_notification_counts_for_tui,
    read_unread_notification_page_for_tui,
)
from sase.ace.tui.actions.changespec._provider import read_changespecs_for_tui
from sase.ace.tui.data_providers._daemon import DaemonAgentsDataProvider
from sase.ace.tui.data_providers._direct import DirectAgentsDataProvider
from sase.ace.tui.util.perf_gates import ace_m2_read_perf_gate_results
from sase.daemon.client import LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult

pytestmark = pytest.mark.slow

_ACE_DAEMON_ENV = {
    "SASE_DAEMON_ACE_AGENTS_READS": "1",
    "SASE_DAEMON_ACE_CHANGESPECS_READS": "1",
    "SASE_DAEMON_ACE_NOTIFICATIONS_READS": "1",
    "SASE_DAEMON_FALLBACK_DIAGNOSTICS": "1",
}


@dataclass(frozen=True)
class _BenchResult:
    value: Any
    request_count: int | None = None


class _CountingLocalDaemonClient(LocalDaemonClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.request_count = 0

    def request(
        self,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        self.request_count += 1
        return super().request(payload, request_id=request_id)


def run_bench(
    *,
    runs: int,
    output: Path | None = None,
    daemon_timeout: float = 0.05,
    notification_limit: int = 25,
) -> dict[str, Any]:
    """Run the ACE read comparison and optionally write a JSON report."""

    if runs < 1:
        raise ValueError("runs must be at least 1")

    report: dict[str, Any] = {
        "tool": "bench_ace_daemon_reads",
        "runs": runs,
        "daemon_timeout_seconds": daemon_timeout,
        "scenarios": {},
    }
    scenarios: dict[str, Callable[[], Any]] = {
        "direct_ace_agents_snapshot": _direct_agents_snapshot,
        "daemon_ace_agents_snapshot": lambda: _daemon_agents_snapshot(daemon_timeout),
        "direct_changespec_snapshot": _direct_changespec_snapshot,
        "daemon_changespec_snapshot": lambda: _daemon_changespec_snapshot(
            daemon_timeout
        ),
        "direct_notification_counts": _direct_notification_counts,
        "daemon_notification_counts": lambda: _daemon_notification_counts(
            daemon_timeout
        ),
        "direct_notification_first_page": lambda: _direct_notification_first_page(
            notification_limit
        ),
        "daemon_notification_first_page": lambda: _daemon_notification_first_page(
            daemon_timeout,
            notification_limit,
        ),
    }

    for name, func in scenarios.items():
        report["scenarios"][name] = _time_scenario(func, runs=runs)
    report["perf_gates"] = ace_m2_read_perf_gate_results(report)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def _time_scenario(func: Callable[[], Any], *, runs: int) -> dict[str, Any]:
    samples_ms: list[float] = []
    last_result: Any = None
    for _ in range(runs):
        start = time.perf_counter()
        last_result = func()
        samples_ms.append((time.perf_counter() - start) * 1000.0)
    samples_sorted = sorted(samples_ms)
    return {
        "samples_ms": samples_ms,
        "median_ms": statistics.median(samples_ms),
        "p95_ms": _percentile(samples_ms, 0.95),
        "min_ms": samples_sorted[0],
        "max_ms": samples_sorted[-1],
        "summary": _result_summary(last_result),
    }


def _direct_agents_snapshot() -> Any:
    with patch.dict(os.environ, {"SASE_NO_DAEMON": "1"}, clear=False):
        return DirectAgentsDataProvider().load_agents()


def _daemon_agents_snapshot(daemon_timeout: float) -> Any:
    with patch.dict(os.environ, _ACE_DAEMON_ENV, clear=False):
        client = _CountingLocalDaemonClient(timeout=daemon_timeout)
        return _BenchResult(
            DaemonAgentsDataProvider(client=client).load_agents(),
            request_count=client.request_count,
        )


def _direct_changespec_snapshot() -> DaemonReadResult[Any]:
    with patch.dict(os.environ, {"SASE_NO_DAEMON": "1"}, clear=False):
        return read_changespecs_for_tui()


def _daemon_changespec_snapshot(daemon_timeout: float) -> Any:
    with patch.dict(os.environ, _ACE_DAEMON_ENV, clear=False):
        client = _CountingLocalDaemonClient(timeout=daemon_timeout)
        return _BenchResult(
            read_changespecs_for_tui(client=client),
            request_count=client.request_count,
        )


def _direct_notification_counts() -> DaemonReadResult[Any]:
    with patch.dict(os.environ, {"SASE_NO_DAEMON": "1"}, clear=False):
        return read_notification_counts_for_tui()


def _daemon_notification_counts(daemon_timeout: float) -> Any:
    with patch.dict(os.environ, _ACE_DAEMON_ENV, clear=False):
        client = _CountingLocalDaemonClient(timeout=daemon_timeout)
        return _BenchResult(
            read_notification_counts_for_tui(client=client),
            request_count=client.request_count,
        )


def _direct_notification_first_page(limit: int) -> DaemonReadResult[Any]:
    with patch.dict(os.environ, {"SASE_NO_DAEMON": "1"}, clear=False):
        return read_unread_notification_page_for_tui(limit=limit)


def _daemon_notification_first_page(
    daemon_timeout: float,
    limit: int,
) -> Any:
    with patch.dict(os.environ, _ACE_DAEMON_ENV, clear=False):
        client = _CountingLocalDaemonClient(timeout=daemon_timeout)
        return _BenchResult(
            read_unread_notification_page_for_tui(client=client, limit=limit),
            request_count=client.request_count,
        )


def _result_summary(result: Any) -> dict[str, Any]:
    request_count: int | None = None
    if isinstance(result, _BenchResult):
        request_count = result.request_count
        result = result.value
    if isinstance(result, DaemonReadResult):
        return {
            "used_daemon": result.used_daemon,
            "fallback_reason": result.fallback_reason,
            "request_count": request_count,
            "debug": result.debug_json()["daemon"],
            "value": _value_summary(result.value),
        }
    summary = _value_summary(result)
    summary["request_count"] = request_count
    return summary


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = percentile * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _value_summary(value: Any) -> dict[str, Any]:
    rows = getattr(value, "rows", None)
    agents = getattr(value, "agents", None)
    notifications = getattr(value, "notifications", None)
    counts = getattr(value, "counts", None)
    return {
        "type": type(value).__name__,
        "row_count": len(rows) if rows is not None else None,
        "agent_count": len(agents) if agents is not None else None,
        "notification_count": (
            len(notifications) if notifications is not None else None
        ),
        "has_counts": counts is not None,
        "used_daemon": getattr(value, "used_daemon", None),
        "fallback_reason": getattr(value, "fallback_reason", None),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark ACE direct and daemon read slices."
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / ".sase" / "perf" / "ace_daemon_reads.json",
    )
    parser.add_argument("--daemon-timeout", type=float, default=0.05)
    parser.add_argument("--notification-limit", type=int, default=25)
    args = parser.parse_args()

    report = run_bench(
        runs=args.runs,
        output=args.output,
        daemon_timeout=args.daemon_timeout,
        notification_limit=args.notification_limit,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
