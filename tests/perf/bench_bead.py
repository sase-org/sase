"""Benchmark the Rust-backed ``sase bead`` implementation.

The bead migration uses this harness for both historical baselines and the
post-migration smoke/regression floor. It measures shell commands, Python
facade calls, single-store reads, and epic work-plan construction.

Run directly:

    python tests/perf/bench_bead.py --runs 5 --output /tmp/bead-bench.json

Use ``--sase-bin /path/to/sase`` to measure an installed console script
instead of ``python -m sase.main.entry`` from the current checkout.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest

from sase.bead import db as db_mod
from sase.bead.config import save_config
from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.bead.work import build_epic_work_plan_from_beads_dir

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


def _time_call(fn: Callable[[], object]) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _fixed_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("SASE_AGENT_NAME", None)
    env.pop("SASE_AGENT_TIMESTAMP", None)
    env.pop("SASE_ARTIFACTS_DIR", None)
    return env


def _sase_command(sase_bin: str | None) -> list[str]:
    if sase_bin:
        return [sase_bin]
    return [sys.executable, "-m", "sase.main.entry"]


def _write_project(root: Path, *, issue_count: int, dependency_count: int) -> None:
    beads_dir = root / "sdd/beads"
    beads_dir.mkdir(parents=True, exist_ok=True)
    save_config(
        beads_dir,
        {"issue_prefix": "bench", "next_counter": issue_count + 1, "owner": ""},
    )
    conn = db_mod.init_db(beads_dir / "beads.db")
    try:
        plans = max(1, issue_count // 10)
        for idx in range(issue_count):
            if idx < plans:
                issue = Issue(
                    id=f"bench-{idx + 1}",
                    title=f"Plan {idx + 1}",
                    status=Status.OPEN,
                    issue_type=IssueType.PLAN,
                    created_at=f"2026-01-01T00:{idx % 60:02d}:00Z",
                    updated_at=f"2026-01-01T00:{idx % 60:02d}:00Z",
                )
            else:
                parent_id = f"bench-{(idx % plans) + 1}"
                issue = Issue(
                    id=f"{parent_id}.{(idx // plans) + 1}",
                    title=f"Phase {idx + 1}",
                    status=Status.OPEN,
                    issue_type=IssueType.PHASE,
                    parent_id=parent_id,
                    created_at=f"2026-01-01T01:{idx % 60:02d}:00Z",
                    updated_at=f"2026-01-01T01:{idx % 60:02d}:00Z",
                )
            db_mod.create_issue(conn, issue)

        issue_ids = [issue.id for issue in db_mod.list_issues(conn)]
        for idx in range(min(dependency_count, max(0, len(issue_ids) - 1))):
            db_mod.add_dependency(
                conn,
                issue_ids[idx + 1],
                issue_ids[idx],
                f"2026-01-02T00:{idx % 60:02d}:00Z",
            )
        from sase.bead.jsonl import export_to_jsonl

        export_to_jsonl(conn, beads_dir / "issues.jsonl")
    finally:
        conn.close()


def _write_work_plan_project(root: Path, *, phase_count: int) -> None:
    beads_dir = root / "sdd/beads"
    beads_dir.mkdir(parents=True, exist_ok=True)
    save_config(
        beads_dir,
        {"issue_prefix": "work", "next_counter": phase_count + 2, "owner": ""},
    )
    conn = db_mod.init_db(beads_dir / "beads.db")
    try:
        epic = Issue(
            id="work-1",
            title="Work planning benchmark",
            status=Status.OPEN,
            issue_type=IssueType.PLAN,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        db_mod.create_issue(conn, epic)
        for idx in range(phase_count):
            phase = Issue(
                id=f"work-1.{idx + 1}",
                title=f"Phase {idx + 1}",
                status=Status.OPEN,
                issue_type=IssueType.PHASE,
                parent_id=epic.id,
                created_at=f"2026-01-01T01:{idx % 60:02d}:00Z",
                updated_at=f"2026-01-01T01:{idx % 60:02d}:00Z",
            )
            db_mod.create_issue(conn, phase)
            if idx > 0:
                db_mod.add_dependency(
                    conn,
                    phase.id,
                    f"work-1.{idx}",
                    f"2026-01-02T00:{idx % 60:02d}:00Z",
                )

        from sase.bead.jsonl import export_to_jsonl

        export_to_jsonl(conn, beads_dir / "issues.jsonl")
    finally:
        conn.close()


def _bench_shell(
    root: Path,
    *,
    runs: int,
    sase_bin: str | None,
) -> dict[str, dict[str, float]]:
    base = _sase_command(sase_bin)
    scenarios = {
        "list": [*base, "bead", "list"],
        "ready": [*base, "bead", "ready"],
        "show": [*base, "bead", "show", "bench-1"],
    }
    results: dict[str, dict[str, float]] = {}
    for name, command in scenarios.items():
        timings: list[float] = []
        for _ in range(runs):

            def _run(command: list[str] = command) -> None:
                subprocess.run(
                    command,
                    cwd=root,
                    env=_fixed_env(),
                    text=True,
                    capture_output=True,
                    check=True,
                )

            timings.append(_time_call(_run))
        results[name] = _summarize(timings)
    return results


def _bench_sidecar_mutation_shell(
    root: Path,
    *,
    runs: int,
    sase_bin: str | None,
) -> dict[str, dict[str, float]]:
    """Measure warm sidecar-store updates, including their local git commit."""
    from sase.sdd.store import write_sdd_store_record

    plans = root / "sase" / "repos" / "plans"
    plans.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=plans, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "SASE Benchmark"], cwd=plans, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "bench@example.invalid"],
        cwd=plans,
        check=True,
    )
    with BeadProject.init(plans, beads_dirname="beads") as project:
        issue = project.create("Mutation benchmark", IssueType.PLAN)
    (plans / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=plans, check=True)
    subprocess.run(
        ["git", "commit", "-m", "seed benchmark"],
        cwd=plans,
        check=True,
        capture_output=True,
    )
    marker_dir = root / ".sase"
    marker_dir.mkdir(parents=True)
    (marker_dir / "checkout.json").write_text(
        json.dumps(
            {
                "project_name": "benchmark",
                "project_key": "benchmark",
                "workspace_num": 1,
                "primary_workspace_dir": str(root),
                "registry_path": str(root / ".sase/registry.json"),
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    write_sdd_store_record(
        root,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "bench/plans",
                    "remote_url": str(root / "plans.git"),
                },
                "research": {
                    "repo": "bench/research",
                    "remote_url": str(root / "research.git"),
                },
            },
        },
    )

    command = [
        *_sase_command(sase_bin),
        "bead",
        "update",
        issue.id,
        "--status",
        "in_progress",
    ]
    timings = []
    for _ in range(runs):
        timings.append(
            _time_call(
                lambda: subprocess.run(
                    command,
                    cwd=root,
                    env=_fixed_env(),
                    text=True,
                    capture_output=True,
                    check=True,
                )
            )
        )
    return {"update_status": _summarize(timings)}


def _bench_project(root: Path, *, runs: int) -> dict[str, dict[str, float]]:
    scenarios: dict[str, Callable[[BeadProject], object]] = {
        "list_issues": lambda project: project.list_issues(),
        "ready": lambda project: project.ready(),
        "show": lambda project: project.show("bench-1"),
    }
    results: dict[str, dict[str, float]] = {}
    for name, fn in scenarios.items():
        timings = [
            _time_call(lambda fn=fn: _with_project(root, fn)) for _ in range(runs)
        ]
        results[name] = _summarize(timings)
    return results


def _with_project(root: Path, fn: Callable[[BeadProject], object]) -> object:
    with BeadProject(root) as project:
        return fn(project)


def _bench_work_plan(root: Path, *, runs: int) -> dict[str, dict[str, float]]:
    timings = [
        _time_call(
            lambda: build_epic_work_plan_from_beads_dir(
                root / "sdd/beads",
                "work-1",
            )
        )
        for _ in range(runs)
    ]
    return {"build_epic_work_plan": _summarize(timings)}


def _bench_preclaim_epic_work(*, runs: int) -> dict[str, dict[str, float]]:
    results: dict[str, dict[str, float]] = {}
    for phase_count in (50, 100, 250):
        batch_timings: list[float] = []
        legacy_timings: list[float] = []
        for _ in range(runs):
            with tempfile.TemporaryDirectory(prefix="sase_bead_preclaim_") as td:
                root = Path(td) / "batch"
                root.mkdir()
                _write_work_plan_project(root, phase_count=phase_count)
                batch_timings.append(
                    _time_call(lambda root=root: _preclaim_batch(root))
                )

            with tempfile.TemporaryDirectory(prefix="sase_bead_preclaim_") as td:
                root = Path(td) / "legacy"
                root.mkdir()
                _write_work_plan_project(root, phase_count=phase_count)
                legacy_timings.append(
                    _time_call(lambda root=root: _preclaim_legacy(root))
                )

        batch_summary = _summarize(batch_timings)
        legacy_summary = _summarize(legacy_timings)
        speedup = 0.0
        batch_median = batch_summary.get("median_ms", 0.0)
        if batch_median:
            speedup = legacy_summary.get("median_ms", 0.0) / batch_median
        results[f"{phase_count}_phases_batch"] = batch_summary
        results[f"{phase_count}_phases_legacy_loop"] = legacy_summary
        results[f"{phase_count}_phases_speedup_vs_legacy"] = {
            "median_x": speedup,
        }
    return results


def _preclaim_batch(root: Path) -> None:
    plan = build_epic_work_plan_from_beads_dir(root / "sdd/beads", "work-1")
    assignments = [
        (assignment.bead_id, assignment.agent_name)
        for wave in plan.waves
        for assignment in wave
    ]
    with BeadProject(root) as project:
        project.preclaim_epic_work("work-1", assignments)


def _preclaim_legacy(root: Path) -> None:
    plan = build_epic_work_plan_from_beads_dir(root / "sdd/beads", "work-1")
    with BeadProject(root) as project:
        for wave in plan.waves:
            for assignment in wave:
                project.show(assignment.bead_id)
                project.update(
                    assignment.bead_id,
                    status="in_progress",
                    assignee=assignment.agent_name,
                )


@contextlib.contextmanager
def _temp_sase_home(home: Path) -> Iterator[None]:
    """Point ``sase_home()`` at *home* and reset the name-registry cache."""
    import sase.agent.names._registry as reg

    prev = os.environ.get("SASE_HOME")
    os.environ["SASE_HOME"] = str(home)
    reg._CACHE_PATH = None
    reg._CACHE_DATA = None
    reg._CACHE_SIGNATURE = None
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("SASE_HOME", None)
        else:
            os.environ["SASE_HOME"] = prev
        reg._CACHE_PATH = None
        reg._CACHE_DATA = None
        reg._CACHE_SIGNATURE = None


@contextlib.contextmanager
def _temp_cwd(path: Path) -> Iterator[None]:
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def _seed_name_registry(count: int) -> None:
    """Write a registry file with *count* (non-stale) planned reservations.

    Planned reservations never look owner-missing, so the seeded entries survive
    the staleness check that ``load_name_registry`` runs on every read. This
    floors the per-launch reserved-name lookup cost against registry size.
    """
    import sase.agent.names._registry as reg
    from sase.agent.names import _registry_store

    entries = {
        f"benchreg{i}": {"reservation_kind": "planned", "name": f"benchreg{i}"}
        for i in range(count)
    }
    data = {
        "schema_version": reg.SCHEMA_VERSION,
        "source_signature": _registry_store._source_signature(),
        "entries": entries,
    }
    path = reg._registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    reg._CACHE_PATH = None
    reg._CACHE_DATA = None
    reg._CACHE_SIGNATURE = None


def _bench_name_validation(
    *,
    runs: int,
    registry_sizes: list[int],
    name_counts: list[int],
) -> dict[str, dict[str, float]]:
    """Floor ``validate_launch_name_requests`` against registry/name counts.

    The one-load fix makes a launch's name validation independent of the number
    of explicit names, so a large ``name_count`` should not scale with anything
    but the single reserved-set load.
    """
    from sase.agent.launch_validation import validate_launch_name_requests

    results: dict[str, dict[str, float]] = {}
    for registry_size in registry_sizes:
        for name_count in name_counts:
            timings: list[float] = []
            for _ in range(runs):
                with tempfile.TemporaryDirectory(prefix="sase_bench_reg_") as td:
                    with _temp_sase_home(Path(td)):
                        _seed_name_registry(registry_size)
                        prompts = [
                            f"%id:benchval{i}\nDo work" for i in range(name_count)
                        ]
                        # Warm the registry cache the way a launch process would.
                        validate_launch_name_requests(prompts)
                        timings.append(
                            _time_call(
                                lambda p=prompts: validate_launch_name_requests(p)
                            )
                        )
            results[f"reg{registry_size}_names{name_count}"] = _summarize(timings)
    return results


@contextlib.contextmanager
def _patched_bead_work_launch() -> Iterator[None]:
    """Patch the launcher/commit/push so ``handle_bead_work`` does no real work."""
    from unittest.mock import patch

    from sase.xprompt.workflow_models import Workflow

    class _FakeResult:
        pid = 1
        workspace_num = 1

    work_phase = Workflow(name="bd/work_phase_bead")
    land_epic = Workflow(name="bd/land_epic")
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch("sase.bead.workspace.resolve_primary_workspace", lambda: None)
        )
        stack.enter_context(
            patch(
                "sase.bead.xprompts.resolve_work_phase_xprompt",
                lambda project=None: work_phase,
            )
        )
        stack.enter_context(
            patch(
                "sase.bead.xprompts.resolve_land_epic_xprompt",
                lambda project=None: land_epic,
            )
        )
        stack.enter_context(
            patch(
                "sase.agent.launcher.launch_agent_from_cwd",
                lambda *a, **k: _FakeResult(),
            )
        )
        stack.enter_context(
            patch(
                "sase.agent.launcher.launch_planned_bead_work_agents",
                lambda **k: [_FakeResult()],
            )
        )
        stack.enter_context(
            patch("sase.bead.sync.commit_bead_work_launch", lambda *a, **k: False)
        )
        stack.enter_context(
            patch("sase.bead.sync.push_bead_work_launch", lambda beads_dir: None)
        )
        yield


def _bench_handle_bead_work(
    *,
    runs: int,
    phase_counts: list[int],
    registry_sizes: list[int],
) -> dict[str, dict[str, float]]:
    """Floor the full parent ``handle_bead_work`` path (launcher/commit patched)."""
    import io

    from sase.bead import cli as bead_cli

    results: dict[str, dict[str, float]] = {}
    for phase_count in phase_counts:
        for registry_size in registry_sizes:
            timings: list[float] = []
            for _ in range(runs):
                with (
                    tempfile.TemporaryDirectory(prefix="sase_bench_bw_") as proj_td,
                    tempfile.TemporaryDirectory(prefix="sase_bench_home_") as home_td,
                ):
                    root = Path(proj_td) / "ws"
                    root.mkdir()
                    _write_work_plan_project(root, phase_count=phase_count)
                    args = argparse.Namespace(
                        id="work-1", dry_run=False, yes=True, no_push=True
                    )
                    with (
                        _temp_sase_home(Path(home_td)),
                        _temp_cwd(root),
                        _patched_bead_work_launch(),
                    ):
                        _seed_name_registry(registry_size)
                        buf = io.StringIO()
                        with (
                            contextlib.redirect_stdout(buf),
                            contextlib.redirect_stderr(buf),
                        ):
                            timings.append(
                                _time_call(lambda a=args: bead_cli.handle_bead_work(a))
                            )
            results[f"phases{phase_count}_reg{registry_size}"] = _summarize(timings)
    return results


def run_benchmark(
    *,
    runs: int,
    issue_count: int,
    dependency_count: int,
    sase_bin: str | None,
    registry_sizes: list[int],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sase_bead_bench_") as td:
        root = Path(td) / "workspace"
        root.mkdir()
        _write_project(root, issue_count=issue_count, dependency_count=dependency_count)
        work_root = Path(td) / "work_plan"
        work_root.mkdir()
        _write_work_plan_project(
            work_root,
            phase_count=max(1, min(issue_count, 2_000)),
        )
        sidecar_root = Path(td) / "sidecar"
        sidecar_root.mkdir()

        return {
            "runs": runs,
            "issue_count": issue_count,
            "dependency_count": dependency_count,
            "registry_sizes": registry_sizes,
            "shell": _bench_shell(root, runs=runs, sase_bin=sase_bin),
            "sidecar_mutation_shell": _bench_sidecar_mutation_shell(
                sidecar_root,
                runs=runs,
                sase_bin=sase_bin,
            ),
            "project": _bench_project(root, runs=runs),
            "work_plan": _bench_work_plan(work_root, runs=runs),
            "preclaim_epic_work": _bench_preclaim_epic_work(runs=runs),
            "name_validation": _bench_name_validation(
                runs=runs,
                registry_sizes=registry_sizes,
                name_counts=[1, 5, 20],
            ),
            "handle_bead_work": _bench_handle_bead_work(
                runs=runs,
                phase_counts=[5, 20],
                registry_sizes=registry_sizes,
            ),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--issues", type=int, default=399)
    parser.add_argument("--dependencies", type=int, default=200)
    parser.add_argument("--sase-bin")
    parser.add_argument(
        "--registry-sizes",
        default="0,500",
        help="Comma-separated agent-name registry sizes to floor launch costs against",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    registry_sizes = [
        int(value) for value in args.registry_sizes.split(",") if value.strip()
    ]
    results = run_benchmark(
        runs=args.runs,
        issue_count=args.issues,
        dependency_count=args.dependencies,
        sase_bin=args.sase_bin,
        registry_sizes=registry_sizes,
    )
    payload = json.dumps(results, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
