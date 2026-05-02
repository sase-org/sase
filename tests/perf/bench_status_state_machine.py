"""Benchmark the status state machine ahead of a possible Rust port.

Phase 4A (sase-19.1) of
``sdd/tales/202604/rust_backend_phase4_status_machine.md``. The intent is to
make the cost of the status state machine visible separately from the
artifact-scan and TUI refresh costs measured by Phase 3, so the Phase 4
go/no-go decision is grounded in numbers.

Workloads
---------

- ``golden`` — the committed ``tests/core_golden/myproj.gp`` corpus
  (4 ChangeSpecs, ~50 lines).
- ``synthetic_<N>`` — a generated ``.gp`` with ``--num-specs`` ChangeSpecs
  templated after the golden file. Stretches the line-walking cost in
  ``read_status_from_lines`` / ``apply_status_update`` past the noise
  floor and captures the worst case for changespecs that live at the end
  of the file.

Scenarios
---------

- ``is_valid_transition`` — pure transition validation
  (``WIP -> Ready`` and ``Ready -> Mailed`` averaged).
- ``remove_workspace_suffix`` — pure regex-driven suffix stripping.
- ``read_status_from_lines`` / ``apply_status_update`` — the line-based
  pure helpers already exposed through ``sase.core.status_facade``.
- ``transition_changespec_status`` — full orchestrator on a temp project
  file with ``validate=True``, including disk I/O. Two flavors:
  - ``transition_changespec_status_wip_to_draft`` (no suffix, no mentor
    flags, simplest path);
  - ``transition_changespec_status_wip_to_ready`` (parses project,
    checks parent constraint, may strip suffix; closest to the cost a
    Rust planner would replace).

After Phase 8E the facade entry points call ``sase_core_rs`` directly,
so each scenario is timed in a single configuration (no backend
toggle).

Marked ``slow`` so it does not run in ``just test``. Run via::

    just bench-status-state-machine
    just bench-status-state-machine --num-specs 200 --runs 20

Or directly::

    pytest -s -m slow tests/perf/bench_status_state_machine.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

from sase.core.status_facade import (
    apply_status_update,
    plan_status_transition,
    read_status_from_lines,
    transition_changespec_status,
)
from sase.core.status_wire import (
    STATUS_WIRE_SCHEMA_VERSION,
    StatusTransitionRequestWire,
)
from sase.status_state_machine.constants import (
    is_valid_transition,
    remove_workspace_suffix,
)

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PRIMARY = REPO_ROOT / "tests" / "core_golden" / "myproj.gp"

_SYNTHETIC_SPEC_TEMPLATE = """\
NAME: spec-{idx}
DESCRIPTION:
  Synthetic spec number {idx}.
  Generated for the Phase 4A status state machine benchmark.
PARENT:
PR: https://example.test/repo/pull/{idx}
BUG: BUG-{idx}
STATUS: WIP
TEST TARGETS: tests/test_spec-{idx}.py
KICKSTART:
  Kick this off carefully.
COMMITS:
  (1) [run] Initial Commit {idx}
      | CHAT: ~/.sase/chats/spec-{idx}.md (0s)
      | DIFF: ~/.sase/diffs/spec-{idx}.diff
HOOKS:
  just lint
      | (1) [260101_120000] PASSED (3s)
COMMENTS:
  [critique] ~/.sase/comments/spec-{idx}.json - (1)
MENTORS:
  (1) profileA[1/1]
      | [260101_130000] profileA:mentor1 - PASSED - (1m0s)
TIMESTAMPS:
  260101_120000 STATUS WIP -> Ready
"""


def _build_synthetic_text(num_specs: int) -> str:
    return "\n\n".join(_SYNTHETIC_SPEC_TEMPLATE.format(idx=i) for i in range(num_specs))


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
        "min_us": vs[0] * 1_000_000.0,
        "median_us": statistics.median(vs) * 1_000_000.0,
        "p95_us": _percentile(vs, 0.95) * 1_000_000.0,
        "max_us": vs[-1] * 1_000_000.0,
    }


def _time_calls(fn: Callable[[], Any], *, runs: int, warmup: int) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return _summarize(samples)


def _measure_pure(
    *,
    label: str,
    text: str,
    target_name: str,
    runs: int,
    warmup: int,
) -> dict[str, Any]:
    """Time the pure helpers (no disk I/O)."""
    lines = text.splitlines(keepends=True)

    def s_is_valid_transition() -> bool:
        # Average a representative pair of valid + invalid checks.
        ok = is_valid_transition("WIP", "Ready")
        bad = is_valid_transition("Submitted", "Draft")
        return ok and not bad

    def s_remove_workspace_suffix() -> str:
        return remove_workspace_suffix("Ready (sase_3)")

    def s_read_status() -> str | None:
        return read_status_from_lines(lines, target_name)

    def s_apply_status() -> str:
        return apply_status_update(lines, target_name, "Ready")

    plan_request = StatusTransitionRequestWire(
        schema_version=STATUS_WIRE_SCHEMA_VERSION,
        changespec_name=target_name,
        old_status="WIP",
        new_status="Ready",
        validate=True,
        parent_status=None,
        blocking_children=(),
        siblings_with_unreverted_children=(),
        existing_names=("spec-a", "spec-b", "spec-c"),
    )

    def s_plan_status_transition() -> bool:
        return plan_status_transition(plan_request).success

    scenarios: dict[str, Callable[[], Any]] = {
        "is_valid_transition": s_is_valid_transition,
        "remove_workspace_suffix": s_remove_workspace_suffix,
        "read_status_from_lines": s_read_status,
        "apply_status_update": s_apply_status,
        "plan_status_transition": s_plan_status_transition,
    }
    results = {
        name: _time_calls(fn, runs=runs, warmup=warmup)
        for name, fn in scenarios.items()
    }

    return {
        "label": label,
        "size_bytes": len(text.encode("utf-8")),
        "lines": len(lines),
        "target_name": target_name,
        "runs": runs,
        "warmup": warmup,
        "scenarios": results,
    }


def _measure_transition(
    *,
    label: str,
    text: str,
    target_name: str,
    runs: int,
    warmup: int,
) -> dict[str, Any]:
    """Time the orchestrator on a temp project file (full disk I/O)."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "myproj.gp"

        def _reset() -> None:
            proj.write_text(text, encoding="utf-8")

        def s_wip_to_draft() -> bool:
            _reset()
            ok, _, _, _ = transition_changespec_status(
                str(proj), target_name, "Draft", validate=True
            )
            return ok

        def s_wip_to_ready() -> bool:
            _reset()
            ok, _, _, _ = transition_changespec_status(
                str(proj), target_name, "Ready", validate=True
            )
            return ok

        scenarios: dict[str, Callable[[], Any]] = {
            "transition_changespec_status_wip_to_draft": s_wip_to_draft,
            "transition_changespec_status_wip_to_ready": s_wip_to_ready,
        }
        results = {
            name: _time_calls(fn, runs=runs, warmup=warmup)
            for name, fn in scenarios.items()
        }

    return {
        "label": label,
        "size_bytes": len(text.encode("utf-8")),
        "target_name": target_name,
        "runs": runs,
        "warmup": warmup,
        "scenarios": results,
    }


def _print_human(report: dict[str, Any]) -> None:
    print()
    print(f"# {report['label']} ({report['size_bytes']} bytes)")
    print(
        f"  runs={int(report['runs'])} warmup={int(report['warmup'])} "
        f"target_name={report['target_name']!r}"
    )
    header = (
        f"{'scenario':<48} {'min_us':>10} "
        f"{'median_us':>12} {'p95_us':>10} {'max_us':>10}"
    )
    print("  " + header)
    print("  " + "-" * len(header))

    for name, summary in report.get("scenarios", {}).items():
        if summary.get("count", 0) == 0:
            continue
        print(
            "  " + f"{name:<48} {summary['min_us']:>10.3f} "
            f"{summary['median_us']:>12.3f} "
            f"{summary['p95_us']:>10.3f} {summary['max_us']:>10.3f}"
        )


def run_bench(
    *,
    runs: int,
    warmup: int,
    num_specs: int,
    output: Path | None,
    skip_synthetic: bool,
    transition_runs: int | None = None,
) -> dict[str, Any]:
    """Run the Phase 4A benchmark and return a structured report.

    Args:
        runs: timed iterations per scenario (used for pure helpers).
        warmup: untimed warmup iterations per scenario.
        num_specs: synthetic workload size.
        output: optional JSON output path.
        skip_synthetic: skip the synthetic workload.
        transition_runs: timed iterations for the transition orchestrator
            scenarios. Defaults to ``min(runs, 20)`` because each
            iteration writes to a fresh tempfile and is much costlier
            than the pure helpers.
    """
    if transition_runs is None:
        transition_runs = min(runs, 20)

    workloads: list[dict[str, Any]] = []

    # Golden corpus
    golden_text = GOLDEN_PRIMARY.read_text(encoding="utf-8")
    workloads.append(
        _measure_pure(
            label="golden_myproj_pure",
            text=golden_text,
            target_name="beta",
            runs=runs,
            warmup=warmup,
        )
    )
    workloads.append(
        _measure_transition(
            label="golden_myproj_transition",
            text=golden_text,
            target_name="beta",
            runs=transition_runs,
            warmup=max(1, warmup // 2),
        )
    )

    if not skip_synthetic:
        synthetic_text = _build_synthetic_text(num_specs)
        # Target the last spec — worst case for line-walkers. The name
        # uses hyphens so :func:`sase.core.changespec.has_suffix` does
        # not match (otherwise WIP→Ready triggers the sibling-revert
        # path, which is a separate cost that should be measured by
        # its own targeted scenario).
        last_target = f"spec-{num_specs - 1}"
        workloads.append(
            _measure_pure(
                label=f"synthetic_{num_specs}_specs_pure",
                text=synthetic_text,
                target_name=last_target,
                runs=runs,
                warmup=warmup,
            )
        )
        workloads.append(
            _measure_transition(
                label=f"synthetic_{num_specs}_specs_transition",
                text=synthetic_text,
                target_name=last_target,
                runs=transition_runs,
                warmup=max(1, warmup // 2),
            )
        )

    report = {
        "tool": "bench_status_state_machine",
        "phase": "4A",
        "rust_available": importlib.util.find_spec("sase_core_rs") is not None,
        "platform": {
            "python": sys.version.split()[0],
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
        },
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
    parser.add_argument("-r", "--runs", type=int, default=200)
    parser.add_argument("-w", "--warmup", type=int, default=20)
    parser.add_argument("-n", "--num-specs", type=int, default=100)
    parser.add_argument(
        "-T",
        "--transition-runs",
        type=int,
        default=None,
        help=(
            "Timed iterations for the transition orchestrator scenarios "
            "(defaults to min(runs, 20) because each iteration writes a "
            "tempfile)."
        ),
    )
    parser.add_argument(
        "-s",
        "--skip-synthetic",
        action="store_true",
        help="Skip the synthetic workload (run only against the golden corpus).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write a JSON report to this path in addition to stdout.",
    )
    return parser


def test_bench_status_state_machine_smoke(tmp_path: Path) -> None:
    """Sanity check the harness on tiny inputs so a regression here is caught."""
    report = run_bench(
        runs=2,
        warmup=1,
        num_specs=3,
        output=tmp_path / "bench.json",
        skip_synthetic=False,
        transition_runs=2,
    )
    assert report["workloads"], "expected at least one workload"
    pure = report["workloads"][0]
    assert "scenarios" in pure
    assert "read_status_from_lines" in pure["scenarios"]
    assert (tmp_path / "bench.json").exists()


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    run_bench(
        runs=args.runs,
        warmup=args.warmup,
        num_specs=args.num_specs,
        output=args.output,
        skip_synthetic=args.skip_synthetic,
        transition_runs=args.transition_runs,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
