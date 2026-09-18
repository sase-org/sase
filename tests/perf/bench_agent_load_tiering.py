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

from sase.core.agent_scan_facade import (  # noqa: E402
    default_agent_artifact_index_path,
    scan_agent_artifacts,
)
from tests.perf.agent_load_tiering_harness import (  # noqa: E402
    DEFAULT_ARCHIVE_ARTIFACT_COUNT,
    SyntheticArchiveFixture,
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
    session_refreshes: int = 10,
    fixture_root: Path | None = None,
    sase_home: Path | None = None,
) -> dict[str, Any]:
    """Materialize the fixture once and return path timing summaries.

    ``sase_home`` benchmarks an existing archive and index (for example the
    real ``~/.sase``) instead of a synthetic fixture. Its paths revalidate
    that index exactly as the TUI does.
    """

    def run(fixture: SyntheticArchiveFixture) -> dict[str, Any]:
        report = benchmark_load_paths(
            fixture,
            queries=queries,
            runs=runs,
            warmup=warmup,
            requested_limit=requested_limit,
            session_refreshes=session_refreshes,
        )
        report["archive_kind"] = "synthetic" if sase_home is None else "existing"
        return report

    if sase_home is not None:
        return run(_existing_archive(sase_home))

    if fixture_root is not None:
        return run(
            build_synthetic_agent_archive(fixture_root, artifact_count=artifact_count)
        )

    with tempfile.TemporaryDirectory(prefix="sase-agent-load-tiering-") as tmp:
        return run(
            build_synthetic_agent_archive(
                Path(tmp) / "fixture", artifact_count=artifact_count
            )
        )


def _existing_archive(sase_home: Path) -> SyntheticArchiveFixture:
    """Describe an existing archive; only its source artifact count is known."""

    home = sase_home.expanduser()
    projects_root = home / "projects"
    return SyntheticArchiveFixture(
        sase_home=home,
        projects_root=projects_root,
        index_path=default_agent_artifact_index_path(home),
        artifact_count=len(scan_agent_artifacts(projects_root).records),
        active_count=0,
        completed_count=0,
        hidden_count=0,
        workflow_count=0,
        provenance_marker_count=0,
    )


def test_bench_agent_load_tiering_smoke(tmp_path: Path) -> None:
    report = run_benchmark(
        artifact_count=72,
        runs=1,
        warmup=0,
        queries=("not machine:apollo",),
        session_refreshes=3,
        fixture_root=tmp_path / "fixture",
    )

    assert report["artifact_count"] == 72
    assert report["archive_kind"] == "synthetic"
    assert set(report["path_totals"]) == {
        "source_scan",
        "index_bounded",
        "index_full_history",
        "production_bounded",
        "production_full_history",
    }
    query_report = report["queries"][0]
    assert query_report["diffs"]["index_full_history"]["missing_count"] == 0
    assert query_report["diffs"]["production_full_history"]["missing_count"] == 0
    assert query_report["diffs"]["production_bounded"]["missing_count"] == 0
    assert query_report["paths"]["source_scan"]["counters"]["marker_files_parsed"] > 0
    assert (
        query_report["paths"]["production_full_history"]["counters"][
            "record_json_decoded"
        ]
        > 0
    )
    bounded = query_report["paths"]["production_bounded"]
    assert bounded["visible_row_count"] > 0
    assert bounded["decoded_records_per_returned_row"] <= 3.0
    requested_limit = report["requested_limit"]
    if requested_limit is not None:
        assert bounded["visible_row_count"] <= requested_limit
    assert (
        "marker_signatures_checked" in query_report["periodic_revalidate"]["counters"]
    )
    session = query_report["refresh_session"]
    assert session["refreshes"] == 3
    assert session["full_history_reads"] == 1
    assert session["stage_timing_ms"]["ordinary_refresh"]["count"] == 3.0
    assert session["artifact_snapshot_cache"]["hits"] >= 1
    assert "p50_ms" in session["unchanged_refresh_ms"]


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
        "--session-refreshes",
        type=int,
        default=10,
        help="Ordinary refreshes in the settled unchanged-query session.",
    )
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=None,
        help="Reuse or create the synthetic fixture under this directory.",
    )
    parser.add_argument(
        "--sase-home",
        type=Path,
        default=None,
        help="Benchmark this existing SASE home's archive instead of a fixture.",
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
        session_refreshes=args.session_refreshes,
        fixture_root=args.fixture_root,
        sase_home=args.sase_home,
    )
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{payload}\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
