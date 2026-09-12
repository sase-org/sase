"""Benchmark the Agents-tab source/index load-tier paths.

Run the Athena-scale default directly with:

    just bench-agent-load-tiering

or:

    .venv/bin/python tests/perf/bench_agent_load_tiering.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402

from tests.perf.agent_load_tiering_harness import (  # noqa: E402
    DEFAULT_ARCHIVE_ARTIFACT_COUNT,
    benchmark_load_paths,
    build_synthetic_agent_archive,
)

pytestmark = pytest.mark.slow


def run_benchmark(
    *,
    artifact_count: int = DEFAULT_ARCHIVE_ARTIFACT_COUNT,
    runs: int = 5,
    warmup: int = 1,
    queries: tuple[str, ...] = ("not machine:apollo",),
    requested_limit: int | None = 100,
    fixture_root: Path | None = None,
) -> dict[str, Any]:
    """Materialize the fixture once and return path timing summaries."""

    if fixture_root is not None:
        fixture = build_synthetic_agent_archive(
            fixture_root,
            artifact_count=artifact_count,
        )
        return benchmark_load_paths(
            fixture,
            queries=queries,
            runs=runs,
            warmup=warmup,
            requested_limit=requested_limit,
        )

    with tempfile.TemporaryDirectory(prefix="sase-agent-load-tiering-") as tmp:
        fixture = build_synthetic_agent_archive(
            Path(tmp) / "fixture",
            artifact_count=artifact_count,
        )
        return benchmark_load_paths(
            fixture,
            queries=queries,
            runs=runs,
            warmup=warmup,
            requested_limit=requested_limit,
        )


def test_bench_agent_load_tiering_smoke(tmp_path: Path) -> None:
    report = run_benchmark(
        artifact_count=72,
        runs=1,
        warmup=0,
        queries=("not machine:apollo",),
        fixture_root=tmp_path / "fixture",
    )

    assert report["artifact_count"] == 72
    assert set(report["path_totals"]) == {
        "source_scan",
        "index_bounded",
        "index_full_history",
    }
    assert report["queries"][0]["diffs"]["index_full_history"]["missing_count"] == 0


def _argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-count",
        type=int,
        default=DEFAULT_ARCHIVE_ARTIFACT_COUNT,
        help="Number of synthetic artifact directories to materialize.",
    )
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        default=None,
        help="Committed Agents-tab query to benchmark; may be repeated.",
    )
    parser.add_argument(
        "--requested-limit",
        type=int,
        default=100,
        help="Viewport limit for the bounded index path.",
    )
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=None,
        help="Reuse or create the synthetic fixture under this directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON report path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    report = run_benchmark(
        artifact_count=args.artifact_count,
        runs=args.runs,
        warmup=args.warmup,
        queries=tuple(args.queries or ("not machine:apollo",)),
        requested_limit=args.requested_limit,
        fixture_root=args.fixture_root,
    )
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{payload}\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
