"""One-shot Phase 6E micro-benchmark.

Compares the Phase 6E targeted Python traversal for ``is_workflow_complete``
against the previous snapshot-backed implementation under both backends.
The synthetic workload deliberately tags every artifact with a real
``workflow_name`` so the predicate has to walk past unrelated workflows
to find its match — this is the structural regression Phase 3H called
out (snapshot path can't short-circuit by workflow name).

Usage::

    .venv/bin/python tests/perf/bench_workflow_complete.py --projects 6 \
        --per-project 200 --runs 5 --warmup 2

Prints the timing of three scenarios per backend run:

- ``is_workflow_complete``  — current (Phase 6E targeted Python).
- ``snapshot_then_filter``  — what the previous snapshot-backed path
  paid: ``scan_agent_artifacts(projects_root, ace-run-only opts)`` plus
  the same filter loop the old implementation used.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
from sase.core.backend import BACKEND_ENV_VAR, DUAL_RUN_ENV_VAR, is_rust_available


def _build(
    home: Path, *, projects: int, per_project: int, workflows: int, target: str
) -> None:
    base_ts = 20260101000000
    ace_run_root = home / ".sase" / "projects"
    ace_run_root.mkdir(parents=True, exist_ok=True)
    target_root_set = False
    for p in range(projects):
        proj = ace_run_root / f"proj{p:03d}" / "artifacts" / "ace-run"
        proj.mkdir(parents=True, exist_ok=True)
        for i in range(per_project):
            ts = str(base_ts + p * per_project + i)
            adir = proj / ts
            adir.mkdir(parents=True, exist_ok=True)
            workflow_name = f"wf_{(p * per_project + i) % workflows}"
            meta: dict[str, Any] = {
                "name": f"agent_{p:03d}_{i:04d}",
                "workflow_name": workflow_name,
                "model": "claude-opus-4-7",
                "pid": 99_999_999,  # dead PID
                "stopped_at": "2026-01-01T00:00:00Z",
            }
            if workflow_name == target and target_root_set:
                meta["parent_timestamp"] = "anything"
            elif workflow_name == target:
                target_root_set = True
            (adir / "agent_meta.json").write_text(json.dumps(meta))
            (adir / "done.json").write_text("{}")


def _summarize(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"count": 0.0}
    s = sorted(samples)
    return {
        "count": float(len(s)),
        "min_ms": s[0] * 1000.0,
        "median_ms": statistics.median(s) * 1000.0,
        "max_ms": s[-1] * 1000.0,
    }


def _time(label: str, fn, *, runs: int, warmup: int) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    summary = _summarize(samples)
    print(
        f"  {label:<48} median={summary.get('median_ms', 0):8.3f} ms  "
        f"min={summary.get('min_ms', 0):8.3f}  max={summary.get('max_ms', 0):8.3f}"
    )
    return summary


def _ace_run_opts() -> AgentArtifactScanOptionsWire:
    return AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
    )


def _snapshot_then_filter(projects_root: Path, target: str) -> bool | None:
    snapshot = scan_agent_artifacts(projects_root, _ace_run_opts())
    matched = []
    for record in snapshot.records:
        if record.workflow_dir_name != "ace-run":
            continue
        meta = record.agent_meta
        if meta is None:
            continue
        if meta.workflow_name == target:
            matched.append(record)
    return True if matched else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-p", "--projects", type=int, default=6)
    parser.add_argument("-n", "--per-project", type=int, default=200)
    parser.add_argument("-w", "--workflows", type=int, default=10)
    parser.add_argument("-r", "--runs", type=int, default=5)
    parser.add_argument("-W", "--warmup", type=int, default=2)
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()

    target_workflow = "wf_0"
    report: dict[str, Any] = {
        "tool": "bench_workflow_complete",
        "phase": "6E",
        "projects": args.projects,
        "per_project": args.per_project,
        "workflows": args.workflows,
        "runs": args.runs,
        "warmup": args.warmup,
        "scenarios": {},
    }

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        _build(
            home,
            projects=args.projects,
            per_project=args.per_project,
            workflows=args.workflows,
            target=target_workflow,
        )
        projects_root = home / ".sase" / "projects"

        from sase.agent.names._lookup import is_workflow_complete

        modes: list[tuple[str, dict[str, str]]] = [
            ("python", {BACKEND_ENV_VAR: "python"}),
            ("rust", {BACKEND_ENV_VAR: "rust"}),
            ("dual_run", {BACKEND_ENV_VAR: "rust", DUAL_RUN_ENV_VAR: "1"}),
        ]
        for backend, env in modes:
            if env.get(BACKEND_ENV_VAR) == "rust" and not is_rust_available():
                print(f"\n# backend={backend!r} (skipped — sase_core_rs not loadable)")
                continue
            print(f"\n# backend={backend!r}")

            def with_env(fn, env=env):
                with patch.dict(os.environ, env):
                    with patch.object(Path, "home", return_value=home):
                        return fn()

            tag = f"backend={backend}"
            report["scenarios"][f"{tag}::is_workflow_complete"] = _time(
                "is_workflow_complete (Phase 6E targeted)",
                lambda: with_env(lambda: is_workflow_complete(target_workflow)),
                runs=args.runs,
                warmup=args.warmup,
            )
            report["scenarios"][f"{tag}::snapshot_then_filter"] = _time(
                "snapshot_then_filter (pre-6E snapshot-backed shape)",
                lambda: with_env(
                    lambda: _snapshot_then_filter(projects_root, target_workflow)
                ),
                runs=args.runs,
                warmup=args.warmup,
            )

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        print(f"\nWrote JSON report -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
