"""Benchmark the agent-artifact scan facade vs current direct loaders.

Phase 3A (sase-18.1) of `../sase_100/plans/202604/rust_backend_phase3_agent_scan.md`.
Establishes the Python baseline measurements that subsequent phases must
beat to justify routing call sites through the Rust scanner.

Workloads
---------

- ``synthetic_<N>``: a generated artifact tree with ``--projects`` projects
  and ``--per-project`` artifact directories per project, each populated
  with ``agent_meta.json`` + ``done.json`` (or ``running.json`` for the
  home project) so the JSON cost is realistic. ``--workflow-fraction``
  artifacts also get a ``workflow_state.json`` and a ``prompt_step``
  marker so workflow loaders have something to do.
- ``home``: when ``--include-home`` is set, the real
  ``~/.sase/projects`` tree is also measured. Off by default so the
  benchmark stays hermetic in CI/development.

Scenarios
---------

For each workload the benchmark times these scenarios:

- ``find_named_agent``: current direct named-agent scan
  (:func:`sase.agent.names._lookup.find_named_agent`).
- ``is_workflow_complete``: current direct workflow-complete check
  (:func:`sase.agent.names._lookup.is_workflow_complete`).
- ``list_running_agents``: current
  :func:`sase.agent.running.list_running_agents`.
- ``list_all_agents``: current
  :func:`sase.agent.running.list_all_agents`.
- ``tui_artifact_load``: ``load_done_agents`` + ``load_running_home_agents``
  + ``load_workflow_states`` + ``load_workflow_agent_steps`` (the artifact
  / workflow portions of ``_load_agents_from_all_sources``).
- ``scan_python_facade``: new
  :func:`sase.core.agent_scan_facade.scan_agent_artifacts` snapshot.
- ``scan_python_facade_no_prompt_steps``: snapshot scan with
  ``include_prompt_step_markers=False``.

Marked ``slow`` so it does not run in ``just test``. Run via::

    just bench-agent-scan
    just bench-agent-scan --projects 5 --per-project 50 --runs 5

Or directly::

    pytest -s -m slow tests/perf/bench_agent_scan.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.core.agent_scan_facade import scan_agent_artifacts_python
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire

pytestmark = pytest.mark.slow


def _build_synthetic_root(
    root: Path,
    *,
    projects: int,
    per_project: int,
    workflow_fraction: float,
) -> Path:
    """Materialize a hermetic synthetic ~/.sase/projects-style tree."""
    root.mkdir(parents=True, exist_ok=True)

    base_ts = 20260101000000
    workflow_step = max(1, int(round(1.0 / max(workflow_fraction, 1e-9))))

    for p in range(projects):
        if p == 0:
            project_name = "home"
        else:
            project_name = f"proj{p:03d}"
        project_dir = root / project_name
        # Project file (.gp) used by RUNNING-field code paths in real life.
        # Empty file is fine for these benchmarks; we don't exercise
        # changespec parsing.
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / f"{project_name}.gp").write_text("", encoding="utf-8")

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        ace_run_dir.mkdir(parents=True, exist_ok=True)

        for i in range(per_project):
            ts = str(base_ts + p * per_project + i)
            artifact_dir = ace_run_dir / ts
            artifact_dir.mkdir(parents=True, exist_ok=True)
            agent_name = f"{project_name}_agent_{i:04d}"

            meta = {
                "name": agent_name,
                "model": "claude-opus-4-7",
                "llm_provider": "claude",
                "vcs_provider": "github",
                "pid": 100000 + p * 1000 + i,
                "approve": False,
                "stopped_at": "2026-01-01T00:00:00Z",
            }
            (artifact_dir / "agent_meta.json").write_text(
                json.dumps(meta), encoding="utf-8"
            )

            if project_name == "home" and i % 2 == 0:
                # Home-mode running marker every other dir.
                (artifact_dir / "running.json").write_text(
                    json.dumps(
                        {
                            "pid": 100000 + p * 1000 + i,
                            "cl_name": "~",
                            "model": "claude-opus-4-7",
                        }
                    ),
                    encoding="utf-8",
                )
            else:
                # Done marker so list_all_agents() and load_done_agents()
                # have something to read.
                (artifact_dir / "done.json").write_text(
                    json.dumps(
                        {
                            "outcome": "completed" if i % 7 else "failed",
                            "finished_at": 1000.0 + i,
                            "cl_name": f"cl_{p:03d}_{i:04d}",
                            "name": agent_name,
                            "model": "claude-opus-4-7",
                        }
                    ),
                    encoding="utf-8",
                )

            if i % workflow_step == 0:
                # Add a workflow_state.json + prompt_step marker so the
                # TUI workflow loader paths have realistic work to do.
                (artifact_dir / "workflow_state.json").write_text(
                    json.dumps(
                        {
                            "workflow_name": f"wf_{i % 3}",
                            "status": "completed" if i % 3 else "running",
                            "appears_as_agent": True,
                            "context": {"cl_name": f"cl_{p:03d}_{i:04d}"},
                            "steps": [
                                {"name": "plan", "status": "completed"},
                                {"name": "code", "status": "completed"},
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                (artifact_dir / "prompt_step_001_plan.json").write_text(
                    json.dumps(
                        {
                            "workflow_name": f"wf_{i % 3}",
                            "step_name": "plan",
                            "status": "completed",
                            "output": {"meta_workspace": str(i)},
                        }
                    ),
                    encoding="utf-8",
                )

    return root


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    idx = max(0, min(n - 1, int(round(pct * (n - 1)))))
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


def _time_calls(
    fn: Callable[[], Any],
    *,
    runs: int,
    warmup: int,
) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return _summarize(samples)


def _run_scenarios(
    *,
    label: str,
    projects_root: Path,
    runs: int,
    warmup: int,
    target_name: str | None,
    workflow_name: str | None,
) -> dict[str, Any]:
    """Time every Phase 3A baseline scenario against *projects_root*.

    The direct loaders read ``Path.home() / ".sase" / "projects"`` rather
    than accepting a root, so we patch ``Path.home()`` for the duration
    of the benchmark to point at the synthetic tree. The new facade
    scanner takes the root explicitly and is not affected by the patch.
    """
    from sase.agent.names._lookup import find_named_agent, is_workflow_complete
    from sase.agent.running import list_all_agents, list_running_agents
    from sase.ace.tui.models._loaders._artifact_loaders import (
        load_done_agents,
        load_running_home_agents,
    )
    from sase.ace.tui.models._loaders._workflow_loaders import (
        load_workflow_agent_steps,
        load_workflow_states,
    )

    fake_home = projects_root.parent

    def _with_fake_home(fn: Callable[[], Any]) -> Any:
        # Patch Path.home() so direct loaders see the synthetic tree.
        with patch("pathlib.Path.home", return_value=fake_home):
            return fn()

    bug_by_cl: dict[str, str | None] = {}
    cl_by_cl: dict[str, str | None] = {}

    def s_find() -> int:
        name = target_name
        if name is None:
            return 0
        result = _with_fake_home(lambda: find_named_agent(name))
        return 1 if result is not None else 0

    def s_workflow_complete() -> int:
        name = workflow_name
        if name is None:
            return 0
        result = _with_fake_home(lambda: is_workflow_complete(name))
        return 1 if result else 0

    def s_list_running() -> int:
        return len(_with_fake_home(list_running_agents))

    def s_list_all() -> int:
        return len(_with_fake_home(list_all_agents))

    def s_tui_load() -> int:
        def _load() -> int:
            done = load_done_agents(bug_by_cl, cl_by_cl)
            home = load_running_home_agents()
            states = load_workflow_states()
            steps, _meta = load_workflow_agent_steps()
            return len(done) + len(home) + len(states) + len(steps)

        return _with_fake_home(_load)

    def s_scan_facade() -> int:
        return len(scan_agent_artifacts_python(projects_root).records)

    def s_scan_facade_no_steps() -> int:
        opts = AgentArtifactScanOptionsWire(include_prompt_step_markers=False)
        return len(scan_agent_artifacts_python(projects_root, opts).records)

    scenarios: dict[str, Callable[[], int]] = {
        "find_named_agent": s_find,
        "is_workflow_complete": s_workflow_complete,
        "list_running_agents": s_list_running,
        "list_all_agents": s_list_all,
        "tui_artifact_load": s_tui_load,
        "scan_python_facade": s_scan_facade,
        "scan_python_facade_no_prompt_steps": s_scan_facade_no_steps,
    }

    results: dict[str, Any] = {
        "label": label,
        "projects_root": str(projects_root),
        "runs": runs,
        "warmup": warmup,
        "target_name": target_name,
        "workflow_name": workflow_name,
        "scenarios": {},
    }

    for name, fn in scenarios.items():
        if name in {"find_named_agent", "is_workflow_complete"} and (
            (name == "find_named_agent" and target_name is None)
            or (name == "is_workflow_complete" and workflow_name is None)
        ):
            results["scenarios"][name] = {"count": 0.0}
            continue
        results["scenarios"][name] = _time_calls(fn, runs=runs, warmup=warmup)

    return results


def _print_human(report: dict[str, Any]) -> None:
    print()
    print(f"# {report['label']}")
    print(f"  projects_root={report['projects_root']}")
    print(
        f"  runs={int(report['runs'])} warmup={int(report['warmup'])} "
        f"target_name={report['target_name']!r} "
        f"workflow_name={report['workflow_name']!r}"
    )
    header = f"{'scenario':<36} {'min_ms':>10} {'median_ms':>12} {'p95_ms':>10} {'max_ms':>10}"
    print("  " + header)
    print("  " + "-" * len(header))
    for name, summary in report["scenarios"].items():
        if summary.get("count", 0) == 0:
            continue
        print(
            "  " + f"{name:<36} {summary['min_ms']:>10.3f} "
            f"{summary['median_ms']:>12.3f} {summary['p95_ms']:>10.3f} "
            f"{summary['max_ms']:>10.3f}"
        )


def run_bench(
    *,
    projects: int,
    per_project: int,
    workflow_fraction: float,
    runs: int,
    warmup: int,
    output: Path | None,
    include_home: bool,
) -> dict[str, Any]:
    workloads: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp) / "projects"
        _build_synthetic_root(
            tmp_root,
            projects=projects,
            per_project=per_project,
            workflow_fraction=workflow_fraction,
        )
        # Pick a name and workflow that exist so find/workflow scenarios
        # do meaningful work (worst case still walks the whole tree).
        target_name = "proj001_agent_0000" if projects > 1 else "home_agent_0000"
        workflow_name = "wf_0"
        workloads.append(
            _run_scenarios(
                label=f"synthetic_{projects}p_{per_project}pp",
                projects_root=tmp_root,
                runs=runs,
                warmup=warmup,
                target_name=target_name,
                workflow_name=workflow_name,
            )
        )

    if include_home:
        home_root = Path.home() / ".sase" / "projects"
        if home_root.exists():
            workloads.append(
                _run_scenarios(
                    label="home_real",
                    projects_root=home_root,
                    runs=runs,
                    warmup=warmup,
                    target_name=None,
                    workflow_name=None,
                )
            )

    report = {
        "tool": "bench_agent_scan",
        "phase": "3A",
        "workloads": workloads,
    }

    for w in workloads:
        _print_human(w)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2))
        print()
        print(f"Wrote JSON report -> {output}")

    return report


def _argparser() -> argparse.ArgumentParser:
    description = (__doc__ or "").splitlines()[0] if __doc__ else ""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--projects", type=int, default=4)
    parser.add_argument("--per-project", type=int, default=40)
    parser.add_argument("--workflow-fraction", type=float, default=0.25)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument(
        "--include-home",
        action="store_true",
        help="Also benchmark the real ~/.sase/projects tree if present.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write a JSON report to this path in addition to stdout.",
    )
    return parser


def test_bench_agent_scan_smoke(tmp_path: Path) -> None:
    """Sanity check the harness on tiny inputs so a regression here is caught."""
    report = run_bench(
        projects=2,
        per_project=3,
        workflow_fraction=0.5,
        runs=2,
        warmup=1,
        output=tmp_path / "bench.json",
        include_home=False,
    )
    assert report["workloads"], "expected at least one workload"
    workload = report["workloads"][0]
    assert "scan_python_facade" in workload["scenarios"]
    assert workload["scenarios"]["scan_python_facade"]["count"] == 2.0
    assert (tmp_path / "bench.json").exists()


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    run_bench(
        projects=args.projects,
        per_project=args.per_project,
        workflow_fraction=args.workflow_fraction,
        runs=args.runs,
        warmup=args.warmup,
        output=args.output,
        include_home=args.include_home,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
