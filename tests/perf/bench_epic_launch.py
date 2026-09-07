"""Synthetic history-scale benchmark for ``sase bead work`` epic launches.

The benchmark builds disposable bead stores and ``SASE_HOME`` trees, seeds
agent history directly in linear time, and patches only the provider/commit
boundary. Cleanup selection, registry freshness, registry rebuilds, forced
reuse cleanup, preclaiming, prompt rendering, and launch timing all use the
production path.

Run directly:

    python tests/perf/bench_epic_launch.py --runs 1 --history-sizes 1000,10000

The default CLI scale is intentionally modest. Pass ``--history-sizes 40000``
and larger slot counts when establishing workstation baselines.
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
from unittest.mock import patch

import pytest

from sase.bead.model import IssueType, PhaseSize
from sase.bead.project import BeadProject

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


@contextlib.contextmanager
def _temp_sase_home(home: Path) -> Iterator[None]:
    import sase.agent.names._registry as reg

    prev = os.environ.get("SASE_HOME")
    os.environ["SASE_HOME"] = str(home)
    reg.reset_name_registry_caches_for_tests()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("SASE_HOME", None)
        else:
            os.environ["SASE_HOME"] = prev
        reg.reset_name_registry_caches_for_tests()


@contextlib.contextmanager
def _temp_cwd(path: Path) -> Iterator[None]:
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


class _SleeperPool:
    def __init__(self) -> None:
        self._procs: list[subprocess.Popen[bytes]] = []

    def spawn(self) -> int:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._procs.append(proc)
        return proc.pid

    def cleanup(self) -> None:
        for proc in self._procs:
            if proc.poll() is not None:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()


def _write_project(
    root: Path, *, phase_count: int, epic_count: int = 1
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    epics: list[tuple[str, tuple[str, ...]]] = []
    with BeadProject.init(root) as project:
        for epic_index in range(epic_count):
            epic = project.create(
                f"Epic launch benchmark {epic_index + 1}",
                IssueType.PLAN,
                tier=None,
                design="sdd/plans/bench.md",
            )
            phase_ids: list[str] = []
            for index in range(phase_count):
                phase = project.create(
                    f"phase-{index + 1}: Benchmark phase {index + 1}",
                    IssueType.PHASE,
                    parent_id=epic.id,
                    size=PhaseSize.SMALL,
                )
                phase_ids.append(phase.id)
                if index:
                    project.add_dependency(phase.id, phase_ids[index - 1])
            epics.append((epic.id, tuple(phase_ids)))
    return tuple(epics)


def _init_local_bare_remote(project_root: Path, remote_root: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=project_root,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "config", "user.email", "bench@example.invalid"],
        cwd=project_root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "bench"], cwd=project_root, check=True
    )
    subprocess.run(
        ["git", "init", "--bare", str(remote_root)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote_root)],
        cwd=project_root,
        check=True,
    )


def _seed_history(
    home: Path,
    *,
    count: int,
    scenario: str,
    epics: tuple[tuple[str, tuple[str, ...]], ...],
    sleepers: _SleeperPool,
) -> dict[str, Any]:
    root = home / "projects/proj/artifacts/ace-run"
    root.mkdir(parents=True, exist_ok=True)
    selected = tuple(
        item
        for epic_id, phase_ids in epics
        for item in _selected_names(scenario, phase_ids, epic_id)
    )
    selected_set = {name for name, _bead_id in selected}
    filler_count = max(0, count - len(selected_set))
    for index in range(filler_count):
        _write_agent_meta(
            root / f"hist-{index:06d}",
            name=f"hist-{index:06d}",
            pid=0,
            done=True,
        )
    for name, bead_id in selected:
        if scenario == "all_active_noop":
            _write_agent_meta(root / f"active-{name}", name=name, bead_id=bead_id)
        elif scenario == "waiting_retry":
            _write_agent_meta(
                root / f"waiting-{name}",
                name=name,
                bead_id=bead_id,
                pid=sleepers.spawn(),
                waiting=True,
            )
        elif scenario == "mixed_family_retry":
            member = f"{name}.member"
            _write_agent_meta(
                root / f"family-{name}",
                name=member,
                bead_id=bead_id,
                done=True,
                family=name,
                family_role="member",
            )
        elif scenario == "terminal_retry":
            _write_agent_meta(
                root / f"done-{name}", name=name, bead_id=bead_id, done=True
            )
    return {
        "history_sources": filler_count + len(selected),
        "selected_slots": len(selected),
        "scenario": scenario,
    }


def _selected_names(
    scenario: str,
    phase_ids: tuple[str, ...],
    epic_id: str,
) -> tuple[tuple[str, str], ...]:
    if scenario in {"fresh_epic", "ordered_four_target_batch"}:
        return ()
    names = [(phase_id, phase_id) for phase_id in phase_ids]
    names.append((f"{epic_id}.land", epic_id))
    return tuple(names)


def _write_agent_meta(
    path: Path,
    *,
    name: str,
    bead_id: str | None = None,
    pid: int | None = None,
    done: bool = False,
    waiting: bool = False,
    family: str | None = None,
    family_role: str | None = None,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {"name": name, "model": "bench"}
    if pid is not None:
        meta["pid"] = pid
    if bead_id is not None:
        meta["bead_id"] = bead_id
        if "." in bead_id:
            meta["phase_bead_id"] = bead_id
            meta["epic_bead_id"] = bead_id.rsplit(".", 1)[0]
        else:
            meta["epic_bead_id"] = bead_id
    if family is not None:
        meta["agent_family"] = family
    if family_role is not None:
        meta["agent_family_role"] = family_role
    (path / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if done:
        (path / "done.json").write_text(
            json.dumps({"outcome": "failed"}),
            encoding="utf-8",
        )
    if waiting:
        (path / "waiting.json").write_text(
            json.dumps({"waiting_for": ["bench-upstream"]}),
            encoding="utf-8",
        )


@contextlib.contextmanager
def _patched_launch_boundary(spawn_times: list[float]) -> Iterator[None]:
    from sase.xprompt.workflow_models import Workflow

    class _FakeResult:
        pid = 1
        workspace_num = 1
        workspace_dir = "/tmp/sase-bench-workspace"
        output_path = "/tmp/sase-bench-output"

    def launch_agent_from_cwd(*_args: object, **_kwargs: object) -> _FakeResult:
        spawn_times.append(time.perf_counter())
        return _FakeResult()

    with (
        patch(
            "sase.bead.xprompts.resolve_work_phase_xprompt",
            lambda project=None: Workflow(name="bd/work_phase_bead"),
        ),
        patch(
            "sase.bead.xprompts.resolve_land_epic_xprompt",
            lambda project=None: Workflow(name="bd/land_epic"),
        ),
        patch("sase.agent.launcher.launch_agent_from_cwd", launch_agent_from_cwd),
        patch("sase.bead.sync.commit_epic_graph_checkpoint", lambda *a, **k: True),
        patch("sase.bead.sync.bead_state_is_clean", lambda _path: True),
        patch("sase.bead.sync.push_bead_work_launch", lambda *a, **k: _PushOutcome()),
    ):
        yield


class _PushOutcome:
    pushed = False
    skipped_no_remote = True
    skipped_locked = False
    error = None
    bead_relocations: tuple[Any, ...] = ()


def _run_one(
    *,
    scenario: str,
    phase_count: int,
    history_size: int,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    from sase.bead import cli as bead_cli

    with (
        tempfile.TemporaryDirectory(
            prefix="sase_epic_launch_proj_", dir=base_dir
        ) as proj_td,
        tempfile.TemporaryDirectory(
            prefix="sase_epic_launch_home_", dir=base_dir
        ) as home_td,
    ):
        project_root = Path(proj_td) / "workspace"
        project_root.mkdir()
        remote_root = Path(proj_td) / "remote.git"
        _init_local_bare_remote(project_root, remote_root)
        home = Path(home_td)
        timing_path = home / "logs/launch_timing.jsonl"
        os.environ["SASE_TUI_LAUNCH_TIMING_PATH"] = str(timing_path)
        epic_count = 4 if scenario == "ordered_four_target_batch" else 1
        epics = _write_project(
            project_root,
            phase_count=phase_count,
            epic_count=epic_count,
        )
        sleepers = _SleeperPool()
        spawn_times: list[float] = []
        try:
            with (
                _temp_sase_home(home),
                _temp_cwd(project_root),
                _patched_launch_boundary(spawn_times),
                contextlib.redirect_stdout(open(os.devnull, "w", encoding="utf-8")),
                contextlib.redirect_stderr(open(os.devnull, "w", encoding="utf-8")),
            ):
                fixture = _seed_history(
                    home,
                    count=history_size,
                    scenario=scenario,
                    epics=epics,
                    sleepers=sleepers,
                )
                start_wall = time.perf_counter()
                start_cpu = time.process_time()
                bead_cli.handle_bead_work(
                    argparse.Namespace(
                        target=[epic_id for epic_id, _phase_ids in epics],
                        dry_run=False,
                        json=False,
                        yes=True,
                        yes_to_all=True,
                        no_push=False,
                        launch_feedback=None,
                        wait=None,
                    )
                )
                end_wall = time.perf_counter()
                end_cpu = time.process_time()
        finally:
            sleepers.cleanup()
            os.environ.pop("SASE_TUI_LAUNCH_TIMING_PATH", None)

        records = _read_timing_records(timing_path)
        summary = next(
            record for record in records if record["event"] == "launch_timing"
        )
        stage_events = [
            record for record in records if record["event"] == "launch_timing_stage"
        ]
        return {
            **fixture,
            "phase_count": phase_count,
            "target_count": epic_count,
            "local_bare_remote": str(remote_root),
            "wall_ms": (end_wall - start_wall) * 1000.0,
            "cpu_ms": (end_cpu - start_cpu) * 1000.0,
            "time_to_first_spawn_ms": (
                (spawn_times[0] - start_wall) * 1000.0 if spawn_times else None
            ),
            "time_to_admission_ms": (
                (spawn_times[-1] - start_wall) * 1000.0 if spawn_times else None
            ),
            "spawn_count": len(spawn_times),
            "summary_stage_count": summary["stage_count"],
            "slow_stage_count": summary["slow_stage_count"],
            "stage_event_count": len(stage_events),
            "stage_totals_ms": _stage_totals(stage_events),
        }


def _read_timing_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _stage_totals(records: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for record in records:
        stage = str(record.get("stage", "unknown"))
        totals[stage] = totals.get(stage, 0.0) + float(record.get("elapsed_ms", 0.0))
    return dict(sorted(totals.items()))


def _git_revision() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _core_revision() -> str | None:
    try:
        from importlib.metadata import version

        return version("sase-core-rs")
    except Exception:
        return None


def run_bench(
    *,
    runs: int,
    history_sizes: list[int],
    phase_counts: list[int],
    scenarios: list[str],
    output: Path | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for scenario in scenarios:
        for history_size in history_sizes:
            for phase_count in phase_counts:
                runs_payload = [
                    _run_one(
                        scenario=scenario,
                        phase_count=phase_count,
                        history_size=history_size,
                        base_dir=base_dir,
                    )
                    for _ in range(runs)
                ]
                key = f"{scenario}_hist{history_size}_slots{phase_count}"
                results[key] = {
                    "runs": runs_payload,
                    "wall": _summarize(run["wall_ms"] / 1000.0 for run in runs_payload),
                    "cpu": _summarize(run["cpu_ms"] / 1000.0 for run in runs_payload),
                    "time_to_first_spawn": _summarize(
                        run["time_to_first_spawn_ms"] / 1000.0
                        for run in runs_payload
                        if run["time_to_first_spawn_ms"] is not None
                    ),
                    "time_to_admission": _summarize(
                        run["time_to_admission_ms"] / 1000.0
                        for run in runs_payload
                        if run["time_to_admission_ms"] is not None
                    ),
                }
    report = {
        "tool": "bench_epic_launch",
        "runs": runs,
        "history_sizes": history_sizes,
        "phase_counts": phase_counts,
        "scenarios": scenarios,
        "python_revision": _git_revision(),
        "core_revision": _core_revision(),
        "results": results,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def _parse_csv_ints(value: str) -> list[int]:
    return [int(item) for item in value.split(",") if item.strip()]


def _parse_csv_strings(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--history-sizes", default="1000,10000")
    parser.add_argument("--phase-counts", default="1,12,40")
    parser.add_argument(
        "--scenarios",
        default=(
            "fresh_epic,all_active_noop,terminal_retry,waiting_retry,"
            "mixed_family_retry,ordered_four_target_batch"
        ),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_bench(
        runs=args.runs,
        history_sizes=_parse_csv_ints(args.history_sizes),
        phase_counts=_parse_csv_ints(args.phase_counts),
        scenarios=_parse_csv_strings(args.scenarios),
        output=args.output,
    )
    if args.output is None:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def test_bench_epic_launch_smoke(tmp_path: Path) -> None:
    report = run_bench(
        runs=1,
        history_sizes=[5],
        phase_counts=[1],
        scenarios=["fresh_epic", "terminal_retry"],
        output=tmp_path / "bench.json",
        base_dir=tmp_path,
    )

    assert report["tool"] == "bench_epic_launch"
    assert (tmp_path / "bench.json").exists()
    assert report["results"]
    first = next(iter(report["results"].values()))["runs"][0]
    assert first["stage_event_count"] > 0
    assert "initial_selection" in first["stage_totals_ms"]


if __name__ == "__main__":
    raise SystemExit(main())
