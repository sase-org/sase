"""Benchmark the Phase 1 Python agent-compose reference path.

Run directly for a quick baseline::

    python tests/perf/bench_agent_compose.py --agents 100 1000 6000 --runs 5

The benchmark is marked slow for pytest and intentionally focuses on the
deterministic Python stages that Phase 2 will port: dead-PID filtering, dedup,
status overrides, ordering, and wire projection.
"""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.models import agent_loader
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models._dedup import (
    dedup_axe_spawned_agents,
    dedup_by_pid,
    dedup_running_vs_workflow,
    dedup_workflow_entries,
    remove_vcs_workspace_claims,
)
from sase.core.agent_compose_facade import compose_python_agents_to_wire

pytestmark = pytest.mark.slow


def _make_agent(idx: int, *, total: int) -> Agent:
    status_cycle = ("RUNNING", "DONE", "FAILED", "WAITING")
    agent_type = AgentType.WORKFLOW if idx % 11 == 0 else AgentType.RUNNING
    pid = 100_000 + idx if status_cycle[idx % len(status_cycle)] != "DONE" else None
    parent_ts = None
    role_suffix = None
    if idx % 17 == 0 and idx > 0:
        parent_idx = max(0, idx - 1)
        parent_ts = f"20260501{parent_idx % 24:02d}{parent_idx % 60:02d}00"
        role_suffix = ".code"
    return Agent(
        agent_type=agent_type,
        cl_name=f"cs_{idx % max(1, total // 25):05d}",
        project_file="/tmp/sase/projects/demo/demo.gp",
        status=status_cycle[idx % len(status_cycle)],
        start_time=None,
        raw_suffix=f"20260501{idx % 24:02d}{idx % 60:02d}00",
        workflow="three_phase" if agent_type == AgentType.WORKFLOW else "ace(run)",
        pid=pid,
        parent_timestamp=parent_ts,
        role_suffix=role_suffix,
        workspace_num=idx % 256,
    )


def _make_agents(count: int) -> list[Agent]:
    return [_make_agent(idx, total=count) for idx in range(count)]


def _time_call(fn: Callable[[], Any], *, runs: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    samples.sort()
    return {
        "median_ms": statistics.median(samples),
        "min_ms": samples[0],
        "max_ms": samples[-1],
    }


def _run_python_pipeline(base_agents: list[Agent]) -> list[Agent]:
    agents = copy.deepcopy(base_agents)
    agents = agent_loader._filter_dead_pids(agents)
    agents = dedup_axe_spawned_agents(agents)
    agents = remove_vcs_workspace_claims(agents)
    agents = dedup_workflow_entries(agents)
    agents = dedup_running_vs_workflow(agents)
    agents = dedup_by_pid(agents)
    agent_loader._apply_status_overrides(agents)
    return agent_loader._sort_and_reorder(agents, [])


def run_benchmark(*, sizes: list[int], runs: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with patch(
        "sase.ace.tui.models.agent_loader.is_process_running",
        return_value=True,
    ):
        for size in sizes:
            base_agents = _make_agents(size)
            rows.append(
                {
                    "agents": size,
                    "dead_pid_filter": _time_call(
                        lambda base_agents=base_agents: agent_loader._filter_dead_pids(
                            copy.deepcopy(base_agents)
                        ),
                        runs=runs,
                    ),
                    "dedup_status_sort": _time_call(
                        lambda base_agents=base_agents: _run_python_pipeline(
                            base_agents
                        ),
                        runs=runs,
                    ),
                    "wire_projection": _time_call(
                        lambda base_agents=base_agents: compose_python_agents_to_wire(
                            copy.deepcopy(base_agents)
                        ),
                        runs=runs,
                    ),
                    "full_reference": _time_call(
                        lambda base_agents=base_agents: compose_python_agents_to_wire(
                            _run_python_pipeline(base_agents)
                        ),
                        runs=runs,
                    ),
                }
            )
    return rows


def test_agent_compose_benchmark_smoke() -> None:
    rows = run_benchmark(sizes=[25], runs=1)
    assert rows[0]["agents"] == 25
    assert rows[0]["full_reference"]["median_ms"] >= 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", nargs="+", type=int, default=[100, 1000, 6000])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = run_benchmark(sizes=args.agents, runs=args.runs)
    payload = {"runs": args.runs, "rows": rows}
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
