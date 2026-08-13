"""Benchmark ``build_detail_header_summary``, the SASE CONTEXT enrichment worker.

Phase `trace` (bead sase-l6.1) of
``plans/202608/sase_context_incremental.md``. Reproduces the two baseline
tables the plan was written against so `stores`, `lanes`, `stream`, and
`immediate` each have a real before/after instead of a component A/B:

- per-resolver cost inside ``build_detail_header_summary``, cold and warm,
  over the first N non-clan agents from ``load_tiered_agents``;
- where ``artifact_file_paths`` (the one resolver with no cache at all)
  spends its time inside ``list_artifact_files``.

"Cold" and "warm" here mean the same thing they mean in the plan: cold is
the first call for a given agent in this process, warm is the immediately
following second call, after every in-process cache (memory-read log,
skill-use log, associated-plan) for that agent is populated. The
per-resolver table is captured by turning on the same ``tui_trace`` spans
production wires (``SASE_TUI_TRACE=1``) and reading back their
``duration_ms`` — the bench and the real capture are the same
instrumentation, so they cannot drift apart.

Marked ``slow`` so it does not run in ``just test``. The smoke test uses a
tiny in-memory agent fixture and stays hermetic; the real baseline needs
``--include-home`` to read live ``~/.sase`` state, the way
``bench_agent_scan.py`` gates its ``home`` workload:

    pytest -s -m slow tests/perf/bench_detail_header_summary.py

    python -m tests.perf.bench_detail_header_summary --include-home \\
        --count 20 --output ~/.sase/perf/detail_header_summary_baseline.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util import trace as tui_trace_mod
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    _TRACE_SPAN_PREFIX,
    build_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_commits import agent_commit_groups
from sase.core.artifact_file_defaults import (
    list_artifact_files,
    synthesize_default_artifact_files,
)
from sase.core.artifact_file_explicit import list_indexed_artifact_files

pytestmark = pytest.mark.slow

# Table 1 row order mirrors the plan's baseline table.
_RESOLVER_SPAN_SUFFIXES = (
    "skill_uses",
    "memory_reads",
    "artifact_file_paths",
    "plan_enrichment",
    "slow_tool_sources",
    "delta_entries",
    "opened_workspaces",
    "xprompts_used",
    "linked_delta_groups",
    "wait_bead_statuses",
    "agent_page_url",
    "bead_display",
)

# agent_commit_groups is not one of build_detail_header_summary's resolvers
# (it is read straight from step_output at render time, off the worker
# entirely), but the plan measures it standalone for comparison: it is the
# free lane the user waits on most, contrasted against the twelve above.
_STANDALONE_SCENARIO = "agent_commit_groups"


def _make_agent(index: int, *, status: str = "DONE") -> Agent:
    """A minimal hermetic Agent for the smoke test (no disk I/O)."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"bench_agent_{index:04d}",
        project_file="/tmp/bench_detail_header_summary.sase",
        status=status,
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        agent_name=f"bench_agent_{index:04d}",
    )


def _summarize(values: Iterable[float]) -> dict[str, float]:
    vs = sorted(values)
    if not vs:
        return {"count": 0.0}
    return {
        "count": float(len(vs)),
        "p50_ms": statistics.median(vs),
        "max_ms": vs[-1],
    }


def _capture_resolver_spans(
    agents: list[Agent], trace_path: Path
) -> list[dict[str, Any]]:
    """Run each agent twice through the traced worker and return the spans.

    Reuses the production ``tui_trace`` instrumentation (bead sase-l6.1)
    rather than re-timing each resolver by hand, so the bench and a real
    ``SASE_TUI_TRACE=1`` capture read the same span names.
    """
    old_flag = os.environ.get(tui_trace_mod.ENV_FLAG)
    old_path = os.environ.get(tui_trace_mod.ENV_PATH)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    if trace_path.exists():
        trace_path.unlink()
    os.environ[tui_trace_mod.ENV_FLAG] = "1"
    os.environ[tui_trace_mod.ENV_PATH] = str(trace_path)
    try:
        for agent in agents:
            build_detail_header_summary(agent)  # cold
            build_detail_header_summary(agent)  # warm
    finally:
        if old_flag is None:
            os.environ.pop(tui_trace_mod.ENV_FLAG, None)
        else:
            os.environ[tui_trace_mod.ENV_FLAG] = old_flag
        if old_path is None:
            os.environ.pop(tui_trace_mod.ENV_PATH, None)
        else:
            os.environ[tui_trace_mod.ENV_PATH] = old_path

    if not trace_path.exists():
        return []
    return [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _resolver_cost_table(agents: list[Agent], trace_path: Path) -> dict[str, Any]:
    records = _capture_resolver_spans(agents, trace_path)
    chunk_size = len(_RESOLVER_SPAN_SUFFIXES) + 1  # + the parent span
    chunks = [records[i : i + chunk_size] for i in range(0, len(records), chunk_size)]

    cold_by_suffix: dict[str, list[float]] = {s: [] for s in _RESOLVER_SPAN_SUFFIXES}
    warm_by_suffix: dict[str, list[float]] = {s: [] for s in _RESOLVER_SPAN_SUFFIXES}
    for call_index, chunk in enumerate(chunks):
        # Each agent is called twice in a row: even call indices are the
        # first (cold) touch, odd indices are the immediately following
        # (warm) touch.
        bucket = cold_by_suffix if call_index % 2 == 0 else warm_by_suffix
        by_span = {row["span"]: row["duration_ms"] for row in chunk}
        for suffix in _RESOLVER_SPAN_SUFFIXES:
            span = f"{_TRACE_SPAN_PREFIX}.{suffix}"
            if span in by_span:
                bucket[suffix].append(by_span[span])

    table: dict[str, Any] = {}
    for suffix in _RESOLVER_SPAN_SUFFIXES:
        cold = _summarize(cold_by_suffix[suffix])
        warm = _summarize(warm_by_suffix[suffix])
        table[suffix] = {
            "cold_p50_ms": cold.get("p50_ms", 0.0),
            "cold_max_ms": cold.get("max_ms", 0.0),
            "warm_p50_ms": warm.get("p50_ms", 0.0),
            "warm_max_ms": warm.get("max_ms", 0.0),
        }

    commit_group_samples = []
    for agent in agents:
        start = time.perf_counter()
        agent_commit_groups(agent)
        commit_group_samples.append((time.perf_counter() - start) * 1000.0)
    commit_group_summary = _summarize(commit_group_samples)
    table[_STANDALONE_SCENARIO] = {
        "cold_p50_ms": commit_group_summary.get("p50_ms", 0.0),
        "cold_max_ms": commit_group_summary.get("max_ms", 0.0),
        "warm_p50_ms": commit_group_summary.get("p50_ms", 0.0),
        "warm_max_ms": commit_group_summary.get("max_ms", 0.0),
    }
    return table


def _time_calls(fn: Callable[[], Any], *, runs: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return _summarize(samples)


def _artifact_file_paths_breakdown(agents: list[Agent], *, runs: int) -> dict[str, Any]:
    """Where ``artifact_file_paths`` spends its time, per the plan's table 2."""
    dirs = [agent.get_artifacts_dir() for agent in agents]
    existing_dirs = [Path(d) for d in dirs if d]

    def _synthesize() -> int:
        return sum(len(synthesize_default_artifact_files(d)) for d in existing_dirs)

    def _indexed() -> int:
        return sum(len(list_indexed_artifact_files(d)) for d in existing_dirs)

    def _total() -> int:
        return sum(len(list_artifact_files(d)) for d in existing_dirs)

    return {
        "synthesize_default_artifact_files": _time_calls(_synthesize, runs=runs),
        "list_indexed_artifact_files": _time_calls(_indexed, runs=runs),
        "list_artifact_files (total)": _time_calls(_total, runs=runs),
        "list_artifact_files (immediately repeated)": _time_calls(_total, runs=runs),
    }


def _print_resolver_table(label: str, table: dict[str, Any]) -> None:
    print()
    print(f"# {label}: per-resolver cost inside build_detail_header_summary")
    header = (
        f"{'resolver':<24} {'cold_p50':>10} {'cold_max':>10} "
        f"{'warm_p50':>10} {'warm_max':>10}"
    )
    print("  " + header)
    print("  " + "-" * len(header))
    for name, row in table.items():
        print(
            "  "
            + f"{name:<24} {row['cold_p50_ms']:>10.1f} {row['cold_max_ms']:>10.1f} "
            f"{row['warm_p50_ms']:>10.1f} {row['warm_max_ms']:>10.1f}"
        )


def _print_breakdown_table(label: str, table: dict[str, Any]) -> None:
    print()
    print(f"# {label}: where artifact_file_paths spends its time")
    header = f"{'component':<44} {'p50_ms':>10} {'max_ms':>10}"
    print("  " + header)
    print("  " + "-" * len(header))
    for name, summary in table.items():
        if summary.get("count", 0) == 0:
            continue
        print(
            "  " + f"{name:<44} {summary['p50_ms']:>10.3f} {summary['max_ms']:>10.3f}"
        )


def run_bench(
    *,
    count: int,
    runs: int,
    output: Path | None,
    include_home: bool,
) -> dict[str, Any]:
    report: dict[str, Any] = {"tool": "bench_detail_header_summary", "workloads": []}

    with tempfile.TemporaryDirectory() as tmp:
        trace_path = Path(tmp) / "trace.jsonl"

        hermetic_agents = [_make_agent(i) for i in range(min(count, 4))]
        hermetic_resolver_table = _resolver_cost_table(hermetic_agents, trace_path)
        hermetic_breakdown = _artifact_file_paths_breakdown(hermetic_agents, runs=runs)
        report["workloads"].append(
            {
                "label": "hermetic_fixture",
                "agent_count": len(hermetic_agents),
                "resolver_table": hermetic_resolver_table,
                "artifact_file_paths_breakdown": hermetic_breakdown,
            }
        )
        _print_resolver_table("hermetic_fixture", hermetic_resolver_table)
        _print_breakdown_table("hermetic_fixture", hermetic_breakdown)

        if include_home:
            from sase.ace.tui.models.agent_loader import load_tiered_agents

            all_agents, _ = load_tiered_agents(full_history=False)
            real_agents = [a for a in all_agents if not a.is_clan_container][:count]
            if real_agents:
                real_resolver_table = _resolver_cost_table(real_agents, trace_path)
                real_breakdown = _artifact_file_paths_breakdown(real_agents, runs=runs)
                report["workloads"].append(
                    {
                        "label": "home_real",
                        "agent_count": len(real_agents),
                        "resolver_table": real_resolver_table,
                        "artifact_file_paths_breakdown": real_breakdown,
                    }
                )
                _print_resolver_table("home_real", real_resolver_table)
                _print_breakdown_table("home_real", real_breakdown)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2))
        print()
        print(f"Wrote JSON report -> {output}")

    return report


def _argparser() -> argparse.ArgumentParser:
    description = (__doc__ or "").splitlines()[0] if __doc__ else ""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--include-home",
        action="store_true",
        help="Also benchmark the real ~/.sase agent set if present.",
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser


def test_bench_detail_header_summary_smoke(tmp_path: Path) -> None:
    """Sanity check the harness stays hermetic and produces every row."""
    report = run_bench(
        count=4, runs=2, output=tmp_path / "bench.json", include_home=False
    )
    assert len(report["workloads"]) == 1
    workload = report["workloads"][0]
    assert workload["label"] == "hermetic_fixture"
    for suffix in _RESOLVER_SPAN_SUFFIXES:
        assert suffix in workload["resolver_table"]
    assert _STANDALONE_SCENARIO in workload["resolver_table"]
    assert "list_artifact_files (total)" in workload["artifact_file_paths_breakdown"]
    assert (tmp_path / "bench.json").exists()


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    run_bench(
        count=args.count,
        runs=args.runs,
        output=args.output,
        include_home=args.include_home,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
