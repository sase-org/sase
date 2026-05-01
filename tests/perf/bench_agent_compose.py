"""Benchmark the agent-compose Python and Rust composition paths.

Run directly for a quick baseline::

    python tests/perf/bench_agent_compose.py --agents 100 1000 6000 --runs 5

The benchmark keeps the original Python pipeline timings as diagnostics and
adds the Phase 6 routed boundary: pre-collected ``RunningClaimWire`` input
composed by Python versus ``sase_core_rs.compose_agent_list`` plus optional
wire-to-``Agent`` hydration.
"""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from sase.ace.tui.models import agent_loader  # noqa: E402
from sase.ace.tui.models.agent import Agent, AgentType  # noqa: E402
from sase.ace.tui.models._loaders import load_agents_from_running_field  # noqa: E402
from sase.ace.tui.models._dedup import (  # noqa: E402
    dedup_axe_spawned_agents,
    dedup_by_pid,
    dedup_running_vs_workflow,
    dedup_workflow_entries,
    remove_vcs_workspace_claims,
)
from sase.core.agent_compose_facade import (  # noqa: E402
    build_agent_compose_input,
    compose_agent_list,
    compose_python_agents_to_wire,
)
from sase.core.agent_compose_wire import RunningClaimWire, agent_from_wire  # noqa: E402
from tests.perf.phase7.metadata import BackendChoice, build_metadata  # noqa: E402
from tests.perf.phase7.summary import compute_speedup, summarize_report  # noqa: E402
from tests._agent_loader_helpers import _empty_artifact_snapshot  # noqa: E402

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


def _time_call(
    fn: Callable[[], Any],
    *,
    runs: int,
    warmup: int = 0,
) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    samples.sort()
    return {
        "count": float(len(samples)),
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


def _make_running_claims(count: int) -> list[RunningClaimWire]:
    project_count = min(8, max(1, count // 25))
    base = datetime(2026, 5, 1, 9, 0, 0)
    claims: list[RunningClaimWire] = []
    for idx in range(count):
        project_idx = idx % project_count
        timestamp = (base + timedelta(seconds=idx)).strftime("%Y%m%d%H%M%S")
        workflow = "workflow(three_phase)" if idx % 11 == 0 else "ace(run)"
        claims.append(
            RunningClaimWire(
                project_file=f"/tmp/sase/projects/proj{project_idx:03d}/proj{project_idx:03d}.gp",
                project_name=f"proj{project_idx:03d}",
                cl_name=f"cs_{idx % max(1, count // 25):05d}",
                workspace_num=idx % 256,
                workspace_dir=f"/tmp/sase/workspaces/sase_{idx % 256}",
                workflow=workflow,
                raw_suffix=timestamp,
                pid=100_000 + idx,
                model="gpt-test",
                llm_provider="codex",
                vcs_provider="git",
                agent_name=f"agent_{idx:05d}",
                approve=idx % 7 == 0,
                hidden=idx % 13 == 0,
            )
        )
    return claims


def _python_compose_from_claims(claims: list[RunningClaimWire]) -> list[Agent]:
    agents = load_agents_from_running_field(
        [],
        {},
        {},
        running_claims=copy.deepcopy(claims),
    )
    pid_liveness = {claim.pid: True for claim in claims if claim.pid is not None}
    return agent_loader._compose_python_agent_list(
        agents,
        [],
        pid_liveness=pid_liveness,
    )


def _python_compose_candidates(
    agents: list[Agent],
    pid_liveness: dict[int, bool],
) -> list[Agent]:
    return agent_loader._compose_python_agent_list(
        copy.deepcopy(agents),
        [],
        pid_liveness=pid_liveness,
    )


def _rust_compose_input_from_claims(claims: list[RunningClaimWire]):
    alive_pids = [claim.pid for claim in claims if claim.pid is not None]
    return build_agent_compose_input(
        running_claims=copy.deepcopy(claims),
        alive_pids=alive_pids,
    )


def _rust_compose_to_agents(claims: list[RunningClaimWire]) -> list[Agent]:
    result = compose_agent_list(_rust_compose_input_from_claims(claims))
    return [agent_from_wire(agent) for agent in result.agents]


def _parity_summary(claims: list[RunningClaimWire]) -> dict[str, Any]:
    python_wire = compose_python_agents_to_wire(_python_compose_from_claims(claims))
    rust_wire = compose_agent_list(_rust_compose_input_from_claims(claims))
    return {
        "agents_match": python_wire.agents == rust_wire.agents,
        "python_agents": len(python_wire.agents),
        "rust_agents": len(rust_wire.agents),
        "rust_dropped": len(rust_wire.dropped),
        "rust_merge_log": len(rust_wire.merge_log),
    }


def _collected_inputs_for_claims(
    claims: list[RunningClaimWire],
):
    return agent_loader._AgentLoaderCompositionInputs(
        project_files=sorted({claim.project_file for claim in claims}),
        changespecs=[],
        bug_by_cl_name={},
        cl_by_cl_name={},
        artifact_snapshot=_empty_artifact_snapshot(),
        running_claims=copy.deepcopy(claims),
        compose_input=_rust_compose_input_from_claims(claims),
    )


def _load_all_agents_backend(
    claims: list[RunningClaimWire], backend: str
) -> list[Agent]:
    inputs = _collected_inputs_for_claims(claims)
    with (
        patch(
            "sase.ace.tui.models.agent_loader._collect_agent_loader_inputs",
            return_value=inputs,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
        patch.dict("os.environ", {"SASE_AGENT_COMPOSE_BACKEND": backend}),
    ):
        return agent_loader.load_all_agents()


def _legacy_python_rows(
    *,
    sizes: list[int],
    runs: int,
    warmup: int,
) -> list[dict[str, Any]]:
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
                        warmup=warmup,
                    ),
                    "dedup_status_sort": _time_call(
                        lambda base_agents=base_agents: _run_python_pipeline(
                            base_agents
                        ),
                        runs=runs,
                        warmup=warmup,
                    ),
                    "wire_projection": _time_call(
                        lambda base_agents=base_agents: compose_python_agents_to_wire(
                            copy.deepcopy(base_agents)
                        ),
                        runs=runs,
                        warmup=warmup,
                    ),
                    "full_reference": _time_call(
                        lambda base_agents=base_agents: compose_python_agents_to_wire(
                            _run_python_pipeline(base_agents)
                        ),
                        runs=runs,
                        warmup=warmup,
                    ),
                }
            )
    return rows


def run_phase7_floor_payload(
    *,
    sizes: list[int],
    runs: int,
    warmup: int = 1,
) -> dict[str, dict[str, Any]]:
    """Return a Phase 7 floor-compatible payload for ``compose_agent_list``."""
    workloads: list[dict[str, Any]] = []
    for size in sizes:
        claims = _make_running_claims(size)
        input_wire = _rust_compose_input_from_claims(claims)
        candidate_agents = load_agents_from_running_field(
            [],
            {},
            {},
            running_claims=copy.deepcopy(claims),
        )
        pid_liveness = {claim.pid: True for claim in claims if claim.pid is not None}
        label = f"synthetic_{size}_running_claims"
        baseline = {
            "load_all_agents_python_backend": _time_call(
                lambda claims=claims: _load_all_agents_backend(claims, "python"),
                runs=runs,
                warmup=warmup,
            ),
            "python_candidate_compose": _time_call(
                lambda candidate_agents=candidate_agents, pid_liveness=pid_liveness: (
                    _python_compose_candidates(
                        candidate_agents,
                        pid_liveness,
                    )
                ),
                runs=runs,
                warmup=warmup,
            ),
            "python_running_claims_full_compose": _time_call(
                lambda claims=claims: _python_compose_from_claims(claims),
                runs=runs,
                warmup=warmup,
            ),
        }
        candidate = {
            "load_all_agents_rust_backend": _time_call(
                lambda claims=claims: _load_all_agents_backend(claims, "rust"),
                runs=runs,
                warmup=warmup,
            ),
            "rust_compose_wire": _time_call(
                lambda input_wire=input_wire: compose_agent_list(input_wire),
                runs=runs,
                warmup=warmup,
            ),
            "rust_compose_to_python_agents": _time_call(
                lambda input_wire=input_wire: [
                    agent_from_wire(agent)
                    for agent in compose_agent_list(input_wire).agents
                ],
                runs=runs,
                warmup=warmup,
            ),
        }
        workloads.append(
            {
                "label": label,
                "baseline": baseline,
                "candidate": candidate,
                "parity": _parity_summary(claims),
                "extra": {
                    "agents": size,
                    "input": "RunningClaimWire only",
                    "python_supplements": "none for this synthetic routed boundary",
                },
            }
        )

    return {
        "compose_agent_list": {
            "tool": "bench_agent_compose",
            "workloads": workloads,
            "extra": {
                "surface": "compose_agent_list",
                "boundary": (
                    "pre-collected RunningClaimWire inputs through Python "
                    "composition vs Rust compose_agent_list"
                ),
            },
        }
    }


def run_benchmark(
    *,
    sizes: list[int],
    runs: int,
    warmup: int = 1,
    include_legacy: bool = True,
) -> dict[str, Any]:
    surface_payload = run_phase7_floor_payload(
        sizes=sizes,
        runs=runs,
        warmup=warmup,
    )["compose_agent_list"]
    return {
        "schema_version": 1,
        "runs": runs,
        "warmup": warmup,
        "surface": "compose_agent_list",
        "workloads": surface_payload["workloads"],
        "legacy_python_rows": (
            _legacy_python_rows(sizes=sizes, runs=runs, warmup=warmup)
            if include_legacy
            else []
        ),
    }


def _build_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = build_metadata(
        tool="bench_agent_compose",
        surface="compose_agent_list",
        workload="synthetic_running_claims",
        backend=BackendChoice.SUMMARY,
        runs=int(payload["runs"]),
        warmup=int(payload["warmup"]),
        extra={
            "boundary": (
                "pre-collected RunningClaimWire inputs; Rust candidate includes "
                "wire-to-Agent hydration in the gated scenario"
            ),
        },
    )
    comparisons: list[dict[str, Any]] = []
    gate_results: list[dict[str, Any]] = []
    for workload in payload["workloads"]:
        comparisons.extend(
            comparison.as_dict()
            for comparison in summarize_report(
                surface="compose_agent_list",
                workload=str(workload["label"]),
                baseline_scenarios=workload["baseline"],
                candidate_scenarios=workload["candidate"],
                baseline_label="python_reference",
                candidate_label="rust_compose",
            )
        )
        for scenario, candidate in workload["candidate"].items():
            baseline_scenario = (
                "load_all_agents_python_backend"
                if scenario == "load_all_agents_rust_backend"
                else "python_candidate_compose"
            )
            baseline = workload["baseline"].get(baseline_scenario)
            gate_results.append(
                compute_speedup(
                    baseline=baseline,
                    candidate=candidate,
                    surface="compose_agent_list",
                    workload=str(workload["label"]),
                    scenario=scenario,
                    baseline_label=baseline_scenario,
                    candidate_label="rust_compose",
                ).as_dict()
            )
    return {
        "metadata": metadata.as_dict(),
        "workloads": payload["workloads"],
        "comparisons": comparisons,
        "gate_results": gate_results,
        "legacy_python_rows": payload["legacy_python_rows"],
    }


def test_agent_compose_benchmark_smoke() -> None:
    payload = run_benchmark(sizes=[25], runs=1, warmup=0)
    workload = payload["workloads"][0]
    assert workload["label"] == "synthetic_25_running_claims"
    assert workload["parity"]["agents_match"] is True
    assert workload["candidate"]["rust_compose_to_python_agents"]["median_ms"] >= 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", nargs="+", type=int, default=[100, 1000, 6000])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument(
        "--no-legacy",
        action="store_true",
        help="Skip legacy Python-only diagnostic timings.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = run_benchmark(
        sizes=args.agents,
        runs=args.runs,
        warmup=args.warmup,
        include_legacy=not args.no_legacy,
    )
    rendered_payload = _build_artifact(payload) if args.output else payload
    rendered = json.dumps(rendered_payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
