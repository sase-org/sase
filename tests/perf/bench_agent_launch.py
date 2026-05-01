"""Benchmark the Rust-backed agent-launch wire and fake-spawn harness.

The harness keeps LLM CLIs out of the loop: each scenario prepares launch
wire records through the production Rust preparation binding, writes output
files under a temp root, and appends fake RUNNING claims to temp ProjectSpec
files. This keeps the benchmark CI-friendly while exercising the launch
planning/preparation boundary users pay before a real provider starts.

Run directly:

    python tests/perf/bench_agent_launch.py --runs 3 --output /tmp/launch.json

Use ``--include-sleeps`` to include the current parent-side fan-out sleeps in
the measured wall time.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_launch_facade import (
    plan_fake_fanout,
    prepare_agent_launch,
)
from sase.core.agent_launch_wire import (
    AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
    AgentLaunchPreparedWire,
    AgentLaunchRequestWire,
)

pytestmark = pytest.mark.slow


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(round(pct * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def _summarize(values: Iterable[float]) -> dict[str, float]:
    vals = sorted(values)
    if not vals:
        return {"count": 0.0}
    return {
        "count": float(len(vals)),
        "min_ms": vals[0] * 1000.0,
        "median_ms": statistics.median(vals) * 1000.0,
        "p95_ms": _percentile(vals, 0.95) * 1000.0,
        "max_ms": vals[-1] * 1000.0,
    }


class _FakeLaunchHost:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.pid = 40000
        self.runner_script = str(root / "run_agent_runner.py")
        Path(self.runner_script).write_text("# fake runner\n", encoding="utf-8")

    def project_file(self, project_name: str) -> str:
        project_dir = self.root / "projects" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        path = project_dir / f"{project_name}.gp"
        if not path.exists():
            path.write_text("NAME: benchmark\n\nRUNNING:\n", encoding="utf-8")
        return str(path)

    def launch(self, request: AgentLaunchRequestWire) -> AgentLaunchPreparedWire:
        (self.root / "tmp").mkdir(parents=True, exist_ok=True)
        prepared = prepare_agent_launch(
            request,
            python_executable="/usr/bin/python",
            runner_script=self.runner_script,
            sase_tmpdir=str(self.root / "tmp"),
            output_root=str(self.root / "workflows"),
        )
        self._fake_spawn(request, prepared)
        return prepared

    def _fake_spawn(
        self,
        request: AgentLaunchRequestWire,
        prepared: AgentLaunchPreparedWire,
    ) -> None:
        self.pid += 1
        Path(prepared.output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(prepared.output_path).write_text("", encoding="utf-8")
        if prepared.claim_request is not None:
            with open(request.project_file, "a", encoding="utf-8") as f:
                f.write(
                    f"  #{prepared.claim_request.workspace_num} | {self.pid} | "
                    f"{request.workflow_name} | {request.cl_name}\n"
                )


def _request(
    host: _FakeLaunchHost,
    *,
    prompt: str,
    timestamp: str,
    cl_name: str = "benchmark",
    project_name: str = "bench",
    workspace_num: int = 2,
    vcs_workflow_type: str | None = None,
    deferred_workspace: bool = False,
) -> AgentLaunchRequestWire:
    workspace_dir = host.root / "workspaces" / f"{project_name}_{workspace_num}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return AgentLaunchRequestWire(
        schema_version=AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        cl_name=cl_name,
        project_file=host.project_file(project_name),
        workspace_dir=str(workspace_dir),
        workspace_num=0 if deferred_workspace else workspace_num,
        workflow_name=f"ace(run)-{timestamp}",
        prompt=prompt,
        timestamp=timestamp,
        project_name=project_name,
        history_sort_key=cl_name,
        vcs_workflow_type=vcs_workflow_type,
        vcs_ref=cl_name if vcs_workflow_type is not None else None,
        deferred_workspace=deferred_workspace,
    )


def _run_plan(
    host: _FakeLaunchHost,
    *,
    launch_kind: str,
    prompts: list[str],
    include_sleeps: bool,
    fanout_sleep_seconds: float = 0.0,
    requires_sequential_naming_wait: bool = False,
    vcs_workflow_type: str | None = None,
    deferred_workspace: bool = False,
) -> dict[str, Any]:
    plan = plan_fake_fanout(
        launch_kind,
        prompts,
        fanout_sleep_seconds=fanout_sleep_seconds,
        requires_sequential_naming_wait=requires_sequential_naming_wait,
    )
    prepared_count = 0
    expected_parent_sleep_ms = (
        max(0, len(plan.slots) - 1) * fanout_sleep_seconds * 1000.0
    )
    for slot in plan.slots:
        if slot.slot_index > 0 and include_sleeps and fanout_sleep_seconds > 0:
            time.sleep(fanout_sleep_seconds)
        timestamp = f"260501_1200{slot.slot_index:02d}"
        host.launch(
            _request(
                host,
                prompt=slot.prompt,
                timestamp=timestamp,
                cl_name="feature/bench" if vcs_workflow_type else "benchmark",
                vcs_workflow_type=vcs_workflow_type,
                deferred_workspace=deferred_workspace,
            )
        )
        prepared_count += 1
        if requires_sequential_naming_wait:
            # The fake runner writes metadata immediately, so this pins the
            # harness stage without adding an artificial timeout.
            (host.root / "agent_meta.json").write_text(
                json.dumps({"name": f"bench.{slot.slot_index}"}),
                encoding="utf-8",
            )
    return {
        "prepared_count": prepared_count,
        "expected_parent_sleep_ms": expected_parent_sleep_ms,
        "requires_sequential_naming_wait": requires_sequential_naming_wait,
    }


def _scenario_functions(
    include_sleeps: bool,
) -> dict[str, Callable[[_FakeLaunchHost], dict[str, Any]]]:
    return {
        "plain_prompt": lambda host: _run_plan(
            host,
            launch_kind="single",
            prompts=["Summarize the repo state"],
            include_sleeps=include_sleeps,
        ),
        "vcs_prompt": lambda host: _run_plan(
            host,
            launch_kind="single",
            prompts=["#gh:feature/bench fix the failing test"],
            include_sleeps=include_sleeps,
            vcs_workflow_type="gh",
        ),
        "model_fanout": lambda host: _run_plan(
            host,
            launch_kind="model",
            prompts=["%model:a do it", "%model:b do it", "%model:c do it"],
            include_sleeps=include_sleeps,
            fanout_sleep_seconds=1.0,
        ),
        "repeat_fanout": lambda host: _run_plan(
            host,
            launch_kind="repeat",
            prompts=["%n:bench.1 do it", "%n:bench.2 do it", "%n:bench.3 do it"],
            include_sleeps=include_sleeps,
            fanout_sleep_seconds=1.0,
        ),
        "multi_prompt": lambda host: _run_plan(
            host,
            launch_kind="multi_prompt",
            prompts=["first segment", "%wait\nsecond segment"],
            include_sleeps=include_sleeps,
            requires_sequential_naming_wait=True,
        ),
        "wait_deferred": lambda host: _run_plan(
            host,
            launch_kind="single",
            prompts=["%wait:previous\ncontinue"],
            include_sleeps=include_sleeps,
            deferred_workspace=True,
        ),
    }


def run_benchmark(*, runs: int, include_sleeps: bool) -> dict[str, Any]:
    scenarios = _scenario_functions(include_sleeps)
    results: dict[str, Any] = {
        "schema_version": AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        "runs": runs,
        "include_sleeps": include_sleeps,
        "scenarios": {},
    }
    for name, fn in scenarios.items():
        timings: list[float] = []
        last_meta: dict[str, Any] = {}
        with tempfile.TemporaryDirectory(prefix=f"sase_launch_bench_{name}_") as td:
            host = _FakeLaunchHost(Path(td))
            for _ in range(runs):
                start = time.perf_counter()
                last_meta = fn(host)
                timings.append(time.perf_counter() - start)
        results["scenarios"][name] = {**_summarize(timings), **last_meta}
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--include-sleeps", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    result = run_benchmark(runs=args.runs, include_sleeps=args.include_sleeps)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
