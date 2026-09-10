"""Benchmark notification-store regression surfaces for the Rust migration.

Phase 1 of ``sdd/plans/202604/notification_rust_migration.md`` used these
workloads to capture the Python baseline. Phase 7 reuses the same harness as
the Rust-backed regression-floor source:

- ``notification_store_5k_load_snapshot``: load and classify a 5k JSONL corpus.
- ``notification_store_5k_mark_dismissed_burst``: mark a burst of agent
  notifications dismissed through the public bulk API.
- ``notification_store_5k_mark_all_read``: run the current full-file read/rewrite.
- ``notification_store_append_plus_rewrite_concurrency``: race append and
  rewrite operations and validate the resulting JSONL remains parseable.
- ``notification_modal_dismiss_burst``: drive the modal dismiss action against a
  loaded 5k inbox while persistence uses the production store backend.

Run directly with::

    pytest -s -m slow tests/perf/bench_notification_store.py

or as a script::

    python tests/perf/bench_notification_store.py --runs 5 --output /tmp/notification-store-baseline.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from sase.notifications.priority import is_priority
from sase.notifications.store import (
    append_notification,
    load_notifications,
    mark_all_read,
    mark_many_dismissed,
    rewrite_notifications,
)

pytestmark = pytest.mark.slow
REPO_ROOT = Path(__file__).resolve().parents[2]
FLOOR_WORKLOAD_LABEL = "synthetic_5k"

# Mostly-dismissed workload: matches the production shape that motivated
# notification-store compaction (~96% dismissed) while staying under the
# Rust store's compaction thresholds (1,000 dismissed rows or 4 MiB) so the
# read cost measured here reflects an uncompacted history-heavy file rather
# than a compaction pass.
MOSTLY_DISMISSED_WORKLOAD_LABEL = "mostly_dismissed_900"
MOSTLY_DISMISSED_SCENARIO = "notification_store_mostly_dismissed_load_snapshot"
MOSTLY_DISMISSED_COUNT = 900
MOSTLY_DISMISSED_FRACTION = 0.96


def _notification_fixture_module() -> Any:
    module_path = REPO_ROOT / "tests" / "fixtures" / "notifications" / "generate.py"
    spec = importlib.util.spec_from_file_location(
        "notification_fixture_generate", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Unable to load notification fixture generator: {module_path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(round(pct * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def _summarize(values: Iterable[float]) -> dict[str, float]:
    vs = sorted(values)
    if not vs:
        return {"count": 0.0}
    return {
        "count": float(len(vs)),
        "min_ms": vs[0] * 1000.0,
        "median_ms": statistics.median(vs) * 1000.0,
        "p95_ms": _percentile(vs, 0.95) * 1000.0,
        "max_ms": vs[-1] * 1000.0,
    }


def _time_calls(fn: Callable[[], Any], *, runs: int, warmup: int) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return _summarize(samples)


@contextmanager
def _patched_store(path: Path):
    import sase.notifications.store as store

    old_dir = store.NOTIFICATIONS_DIR
    old_file = store.NOTIFICATIONS_FILE
    old_cache = dict(store._LOAD_CACHE)
    store.NOTIFICATIONS_DIR = str(path.parent)
    store.NOTIFICATIONS_FILE = str(path)
    store._LOAD_CACHE.clear()
    try:
        yield
    finally:
        store.NOTIFICATIONS_DIR = old_dir
        store.NOTIFICATIONS_FILE = old_file
        store._LOAD_CACHE.clear()
        store._LOAD_CACHE.update(old_cache)


def _prepare_corpus(
    path: Path, count: int, *, dismissed_fraction: float | None = None
) -> None:
    fixture_module = _notification_fixture_module()
    fixture_module.write_jsonl(
        path,
        fixture_module.synthetic_rows(count, dismissed_fraction=dismissed_fraction),
    )


def _copy_corpus(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())


def _snapshot_counts() -> dict[str, int]:
    notifications = load_notifications()
    counts = {"priority": 0, "rest": 0, "muted": 0}
    for notification in notifications:
        if notification.muted:
            counts["muted"] += 1
        elif is_priority(notification):
            counts["priority"] += 1
        else:
            counts["rest"] += 1
    return counts


def _run_append_plus_rewrite_race() -> int:
    notifications = load_notifications(include_dismissed=True)

    def append_rows() -> None:
        for idx in range(25):
            append_notification(
                notifications[idx].__class__(
                    id=f"concurrent-append-{idx}",
                    timestamp="2026-04-30T12:59:59+00:00",
                    sender="bench",
                )
            )

    def rewrite_rows() -> None:
        rewritten = load_notifications(include_dismissed=True)
        for notification in rewritten[:250]:
            notification.read = True
        rewrite_notifications(rewritten)

    appender = threading.Thread(target=append_rows)
    rewriter = threading.Thread(target=rewrite_rows)
    appender.start()
    rewriter.start()
    appender.join(timeout=10)
    rewriter.join(timeout=10)
    return len(load_notifications(include_dismissed=True))


def _run_modal_dismiss_burst() -> int:
    from sase.ace.tui.modals.notification_modal import NotificationModal

    notifications = load_notifications()
    modal = NotificationModal(notifications)
    return modal._bulk_dismiss_notifications_by_index(25)


def _time_mostly_dismissed_load_snapshot(
    *, runs: int, warmup: int, count: int, dismissed_fraction: float
) -> dict[str, float]:
    """Time a snapshot read on a store shaped like the production incident.

    Unlike ``run_bench``'s ``synthetic_5k`` workload (~5% dismissed), this
    corpus is mostly-dismissed so a regression in how the read path scans
    or classifies dead rows fails loudly even before compaction thresholds
    are crossed.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "notifications.jsonl"
        _prepare_corpus(path, count, dismissed_fraction=dismissed_fraction)
        with _patched_store(path):
            return _time_calls(_snapshot_counts, runs=runs, warmup=warmup)


def run_bench(
    *,
    runs: int,
    warmup: int,
    count: int,
    output: Path | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "source" / "notifications.jsonl"
        _prepare_corpus(source, count)

        def with_fresh_store(fn: Callable[[], Any]) -> Callable[[], Any]:
            def wrapped() -> Any:
                store_path = tmp / "work" / f"{time.time_ns()}" / "notifications.jsonl"
                _copy_corpus(source, store_path)
                with _patched_store(store_path):
                    return fn()

            return wrapped

        load_path = tmp / "load" / "notifications.jsonl"
        _copy_corpus(source, load_path)
        with _patched_store(load_path):
            load_snapshot = _time_calls(_snapshot_counts, runs=runs, warmup=warmup)

        dismiss_ids = [f"synthetic-{idx:06d}" for idx in range(1, min(count, 500), 7)]

        def mark_dismissed_burst() -> int:
            return mark_many_dismissed(dismiss_ids)

        scenarios = {
            "notification_store_5k_load_snapshot": load_snapshot,
            "notification_store_5k_mark_dismissed_burst": _time_calls(
                with_fresh_store(mark_dismissed_burst), runs=runs, warmup=warmup
            ),
            "notification_store_5k_mark_all_read": _time_calls(
                with_fresh_store(mark_all_read), runs=runs, warmup=warmup
            ),
            "notification_store_append_plus_rewrite_concurrency": _time_calls(
                with_fresh_store(_run_append_plus_rewrite_race),
                runs=runs,
                warmup=warmup,
            ),
            "notification_modal_dismiss_burst": _time_calls(
                with_fresh_store(_run_modal_dismiss_burst),
                runs=runs,
                warmup=warmup,
            ),
        }

    report = {
        "count": count,
        "runs": runs,
        "warmup": warmup,
        "scenarios": scenarios,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def run_phase7_floor_payload(
    *,
    runs: int,
    warmup: int,
    count: int,
) -> dict[str, Any]:
    """Return a Phase 7 checker-compatible payload for notification anchors."""
    report = run_bench(runs=runs, warmup=warmup, count=count)
    mostly_dismissed_summary = _time_mostly_dismissed_load_snapshot(
        runs=runs,
        warmup=warmup,
        count=MOSTLY_DISMISSED_COUNT,
        dismissed_fraction=MOSTLY_DISMISSED_FRACTION,
    )
    return {
        "notification_store": {
            "workloads": [
                {
                    "label": FLOOR_WORKLOAD_LABEL,
                    "baseline": {},
                    "candidate": report["scenarios"],
                },
                {
                    "label": MOSTLY_DISMISSED_WORKLOAD_LABEL,
                    "baseline": {},
                    "candidate": {
                        MOSTLY_DISMISSED_SCENARIO: mostly_dismissed_summary,
                    },
                },
            ]
        }
    }


def _print_human(report: dict[str, Any]) -> None:
    print()
    print(f"# notification store corpus={report['count']} runs={report['runs']}")
    header = f"{'scenario':<52} {'min_ms':>10} {'median_ms':>12} {'p95_ms':>10} {'max_ms':>10}"
    print(header)
    print("-" * len(header))
    for name, summary in report["scenarios"].items():
        print(
            f"{name:<52} {summary['min_ms']:>10.3f} "
            f"{summary['median_ms']:>12.3f} {summary['p95_ms']:>10.3f} "
            f"{summary['max_ms']:>10.3f}"
        )


def test_bench_smoke() -> None:
    report = run_bench(runs=1, warmup=0, count=100)
    assert set(report["scenarios"]) == {
        "notification_store_5k_load_snapshot",
        "notification_store_5k_mark_dismissed_burst",
        "notification_store_5k_mark_all_read",
        "notification_store_append_plus_rewrite_concurrency",
        "notification_modal_dismiss_burst",
    }


def test_phase7_floor_payload_shape() -> None:
    payload = run_phase7_floor_payload(runs=1, warmup=0, count=100)
    workloads = payload["notification_store"]["workloads"]
    assert workloads[0]["label"] == FLOOR_WORKLOAD_LABEL
    assert "notification_modal_dismiss_burst" in workloads[0]["candidate"]
    assert workloads[1]["label"] == MOSTLY_DISMISSED_WORKLOAD_LABEL
    assert MOSTLY_DISMISSED_SCENARIO in workloads[1]["candidate"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--count", type=int, default=5_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    report = run_bench(
        runs=args.runs,
        warmup=args.warmup,
        count=args.count,
        output=args.output,
    )
    _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
