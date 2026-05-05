"""Benchmark the unified artifact graph integration path.

The harness builds a deterministic mixed SASE fixture in a temp directory,
then measures the Rust-backed Python facade operations that Epic 6 treats as
the integrated artifact quality gate:

    python tests/perf/bench_artifact_graph.py --runs 3 --output /tmp/artifacts.json

The timings are intentionally descriptive rather than workstation-gating. The
assertions only cover integration correctness, bounded modal behavior, and
absence of broad scans in the fake TUI graph.
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
        if str(row["operation"]).startswith("modal_open:")
    ]
    assert modal_rows
    assert all(row["query_counts"]["calls"] == 1 for row in modal_rows)


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
