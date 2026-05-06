"""Benchmark the unified artifact graph integration path.

The harness builds a deterministic mixed SASE fixture in a temp directory,
then measures the Rust-backed Python facade operations and startup sentinel
that Epic 6 treats as the integrated artifact quality gate:

    python tests/perf/bench_artifact_graph.py --runs 3 --output /tmp/artifacts.json

The timings are intentionally descriptive rather than workstation-gating. The
assertions only cover integration correctness, bounded query behavior, bounded
modal behavior, and absence of broad startup graph calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME

if __package__:
    from .artifact_graph import run_benchmark
else:
    from artifact_graph import run_benchmark

pytestmark = pytest.mark.slow


def test_artifact_graph_benchmark_smoke() -> None:
    pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    result = run_benchmark(
        runs=1,
        project_count=2,
        bead_count=4,
        agent_count=4,
        modal_linked_count=12,
    )

    errors = [
        error
        for measurement in result["measurements"]
        for error in measurement.get("errors", [])
    ]
    assert errors == []
    modal_rows = [
        row
        for row in result["measurements"]
        if str(row["operation"]).startswith("modal_open:paged:")
    ]
    assert modal_rows
    assert all(row["query_counts"]["artifact_show_paged"] == 1 for row in modal_rows)
    assert all(row["query_counts"]["artifact_show"] == 0 for row in modal_rows)
    assert all(row["result_count"] <= 40 for row in modal_rows)

    missing_modal = [
        row
        for row in result["measurements"]
        if row["operation"]
        == "modal_open:missing_artifact_targeted_refresh:changespec:current"
    ]
    assert missing_modal
    assert all(row["query_counts"]["artifact_show_paged"] == 2 for row in missing_modal)
    assert all(row["mutation_counts"]["calls"] == 1 for row in missing_modal)

    startup_rows = [
        row
        for row in result["measurements"]
        if str(row["operation"]).startswith("startup_contract:")
    ]
    assert {row["operation"] for row in startup_rows} == {
        "startup_contract:no_broad_artifact_graph_calls",
        "startup_contract:missing_index_no_broad_artifact_graph_calls",
    }
    assert all(row["query_counts"]["calls"] == 0 for row in startup_rows)

    by_operation = {row["operation"]: row for row in result["measurements"]}
    assert (
        by_operation["targeted_agent_artifact_burst"]["mutation_counts"]["calls"] == 1
    )
    assert (
        by_operation["artifact_show_paged:high_degree_children"]["result_count"] == 10
    )
    assert by_operation["artifact_search:global_limited"]["result_count"] <= 12
    assert (
        by_operation["artifact_summary:visible_rows_batch"]["query_counts"]["calls"]
        == 1
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--projects", type=int, default=4)
    parser.add_argument("--beads", type=int, default=30)
    parser.add_argument("--agents", type=int, default=30)
    parser.add_argument("--modal-linked", type=int, default=240)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = run_benchmark(
        runs=args.runs,
        project_count=args.projects,
        bead_count=args.beads,
        agent_count=args.agents,
        modal_linked_count=args.modal_linked,
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
