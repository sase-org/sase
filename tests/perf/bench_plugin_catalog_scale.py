"""Non-TUI scale bench for plugin catalog fetch pages and latest enrichment.

Run explicitly with::

    pytest -s -m slow tests/perf/bench_plugin_catalog_scale.py
    python -m tests.perf.bench_plugin_catalog_scale --write-baseline

Wall-clock budgets are recorded, not enforced. Operation-count curves
(fetch calls, installed-version lookups, scan work, page count) are the
measuring stick later phases compare against.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.perf.plugin_catalog_scale import (
    BASELINE_PATH,
    CATALOG_SCALE_SIZES,
    expected_enrich_ops,
    expected_fetch_pages,
    measure_enrich_cost,
    measure_fetch_pages,
    merge_baseline_section,
)

pytestmark = pytest.mark.slow


def _print_curve(title: str, rows: dict[str, dict[str, float]]) -> None:
    print(f"\n{title}", file=sys.stderr)
    print(
        f"  {'n':>6} {'p50_ms':>10} {'p95_ms':>10} {'max_ms':>10} {'ops':>12}",
        file=sys.stderr,
    )
    for size, stats in rows.items():
        ops = stats.get("scan_work", stats.get("pages", 0.0))
        print(
            f"  {int(size):>6d} {stats['p50_ms']:>10.2f} {stats['p95_ms']:>10.2f} "
            f"{stats['max_ms']:>10.2f} {ops:>12.0f}",
            file=sys.stderr,
        )


def run_enrich_curve(
    *,
    sizes: tuple[int, ...] = CATALOG_SCALE_SIZES,
    runs: int = 3,
    warmup: int = 1,
) -> dict[str, dict[str, float]]:
    """Measure ``enrich_with_latest`` at each catalog size."""
    rows: dict[str, dict[str, float]] = {}
    for size in sizes:
        stats = measure_enrich_cost(size, runs=runs, warmup=warmup)
        expected = expected_enrich_ops(size)
        assert stats["fetch_calls"] == expected["fetch_calls"], (
            f"enrich fetch_calls at n={size}: {stats['fetch_calls']} "
            f"!= {expected['fetch_calls']}"
        )
        assert stats["installed_lookups"] == expected["installed_lookups"], (
            f"enrich installed_lookups at n={size}: {stats['installed_lookups']} "
            f"!= {expected['installed_lookups']}"
        )
        assert stats["scan_work"] == expected["scan_work"], (
            f"enrich scan_work at n={size}: {stats['scan_work']} "
            f"!= {expected['scan_work']}"
        )
        rows[str(size)] = stats
    _print_curve("enrich_with_latest (CPU, stubbed fetch):", rows)
    return rows


def run_fetch_curve(
    *,
    sizes: tuple[int, ...] = CATALOG_SCALE_SIZES,
    runs: int = 3,
    warmup: int = 1,
) -> dict[str, dict[str, float]]:
    """Measure ``fetch_catalog_payload`` parse cost and page count."""
    rows: dict[str, dict[str, float]] = {}
    for size in sizes:
        stats = measure_fetch_pages(size, runs=runs, warmup=warmup)
        assert stats["pages"] == float(expected_fetch_pages(size)), (
            f"fetch pages at n={size}: {stats['pages']} != {expected_fetch_pages(size)}"
        )
        assert stats["returned_entries"] == float(size), (
            f"fetch returned_entries at n={size}: {stats['returned_entries']} != {size}"
        )
        rows[str(size)] = stats
    _print_curve("fetch_catalog_payload page parse:", rows)
    return rows


def test_bench_enrich_and_fetch_scale_curves() -> None:
    """Record enrich/fetch cost curves at 10/250/1000/2000 entries."""
    enrich = run_enrich_curve()
    fetch = run_fetch_curve()
    # Doubling n from 1000 to 2000 must quadruple scan work (n² lookups).
    assert enrich["2000"]["scan_work"] / enrich["1000"]["scan_work"] == 4.0
    assert fetch["2000"]["pages"] / fetch["1000"]["pages"] == 2.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Merge measured enrich/fetch rows into the committed baseline JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the live report JSON to this path.",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    args = parser.parse_args(argv)

    report: dict[str, Any] = {
        "enrich": run_enrich_curve(runs=args.runs, warmup=args.warmup),
        "fetch": run_fetch_curve(runs=args.runs, warmup=args.warmup),
    }
    if args.write_baseline:
        merge_baseline_section("enrich", report["enrich"])
        merge_baseline_section("fetch", report["fetch"])
        print(f"wrote enrich/fetch rows to {BASELINE_PATH}", file=sys.stderr)
    if args.output is not None:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
