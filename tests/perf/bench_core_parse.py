"""Benchmark sase.core.parse_project_bytes paths.

Phase 1E (sase-16.5) of `sdd/plans/202604/rust_backend_phase1.md`. Times the
end-to-end cost of parsing project bytes through every code path that
production callers might touch:

- Python direct: `parse_project_file_python(path)` reading from disk
  (the Python file-path API kept for unported helpers).
- Rust direct: `sase_core_rs.parse_project_bytes(path, data)` if the
  PyO3 extension is importable.
- Rust facade: `sase.core.parser_facade.parse_project_bytes(path, data)`
  — the only ported path post-Phase-8 (PyO3 call + dict rehydration into
  `ChangeSpecWire` dataclasses on the Python side).

Workloads:

- `golden`: the committed `tests/core_golden/myproj.gp` (small).
- `synthetic`: a generated multi-spec file with `--num-specs` repetitions
  to stretch the parsers past the noise floor.

Marked ``slow`` so it does not run in `just test`. Run via::

    just bench-core
    just bench-core --num-specs 200 --runs 5

Or:

    pytest -s -m slow tests/perf/bench_core_parse.py

The benchmark always returns the Python facade output to the caller, so
asserting on field counts is safe across backends.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

from sase.ace.changespec.parser import parse_project_file_python
from sase.core import parser_facade


def _load_rust_module() -> Any | None:
    if importlib.util.find_spec("sase_core_rs") is None:
        return None
    return importlib.import_module("sase_core_rs")


pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "tests" / "core_golden"
GOLDEN_PRIMARY = GOLDEN_DIR / "myproj.gp"

_SYNTHETIC_SPEC_TEMPLATE = """\
## ChangeSpec
NAME: spec_{idx}
DESCRIPTION:
  Synthetic spec number {idx}.
  Generated for the Phase 1E benchmark.
PARENT:
PR: https://example.test/repo/pull/{idx}
BUG: BUG-{idx}
STATUS: WIP
TEST TARGETS: tests/test_spec_{idx}.py
KICKSTART:
  Kick this off carefully.
COMMITS:
  (1) [run] Initial Commit {idx}
      | CHAT: ~/.sase/chats/spec_{idx}.md (0s)
      | DIFF: ~/.sase/diffs/spec_{idx}.diff
HOOKS:
  just lint
      | (1) [260101_120000] PASSED (3s)
COMMENTS:
  [critique] ~/.sase/comments/spec_{idx}.json - (1)
MENTORS:
  (1) profileA[1/1]
      | [260101_130000] profileA:mentor1 - PASSED - (1m0s)
TIMESTAMPS:
  260101_120000 STATUS WIP -> Ready
DELTAS:
  + src/spec_{idx}.py
"""


def _build_synthetic_bytes(num_specs: int) -> bytes:
    return "\n\n".join(
        _SYNTHETIC_SPEC_TEMPLATE.format(idx=i) for i in range(num_specs)
    ).encode("utf-8")


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    idx = max(0, min(n - 1, int(round(pct * (n - 1)))))
    return sorted_vals[idx]


def _summarize(values: Iterable[float]) -> dict[str, float]:
    vs = sorted(values)
    if not vs:
        return {"count": 0}
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


def _measure_workload(
    *,
    label: str,
    path: str,
    data: bytes,
    runs: int,
    warmup: int,
) -> dict[str, Any]:
    rust_module = _load_rust_module()

    def py_direct() -> int:
        return len(parse_project_file_python(path))

    def rust_direct() -> int:
        assert rust_module is not None
        return len(rust_module.parse_project_bytes(path, data))

    def rust_facade() -> int:
        return len(parser_facade.parse_project_bytes(path, data))

    results: dict[str, Any] = {
        "label": label,
        "path": path,
        "size_bytes": len(data),
        "runs": runs,
        "warmup": warmup,
        "rust_available": rust_module is not None,
        "scenarios": {},
    }

    results["scenarios"]["python_direct"] = _time_calls(
        py_direct, runs=runs, warmup=warmup
    )
    if rust_module is not None:
        results["scenarios"]["rust_direct"] = _time_calls(
            rust_direct, runs=runs, warmup=warmup
        )
        results["scenarios"]["rust_facade"] = _time_calls(
            rust_facade, runs=runs, warmup=warmup
        )
    return results


def _print_human(report: dict[str, Any]) -> None:
    print()
    print(f"# {report['label']} ({report['size_bytes']} bytes)")
    print(f"  runs={int(report['runs'])} warmup={int(report['warmup'])}")
    print(f"  rust_available={report['rust_available']}")
    header = f"{'scenario':<18} {'min_ms':>10} {'median_ms':>12} {'p95_ms':>10} {'max_ms':>10}"
    print("  " + header)
    print("  " + "-" * len(header))
    for name, summary in report["scenarios"].items():
        if summary.get("count", 0) == 0:
            continue
        print(
            "  " + f"{name:<18} {summary['min_ms']:>10.3f} "
            f"{summary['median_ms']:>12.3f} {summary['p95_ms']:>10.3f} "
            f"{summary['max_ms']:>10.3f}"
        )


def run_bench(
    *,
    runs: int,
    warmup: int,
    num_specs: int,
    output: Path | None,
    skip_synthetic: bool,
) -> dict[str, Any]:
    workloads: list[dict[str, Any]] = []

    golden_data = GOLDEN_PRIMARY.read_bytes()
    workloads.append(
        _measure_workload(
            label="golden_myproj",
            path=str(GOLDEN_PRIMARY),
            data=golden_data,
            runs=runs,
            warmup=warmup,
        )
    )

    if not skip_synthetic:
        synthetic = _build_synthetic_bytes(num_specs)
        with tempfile.NamedTemporaryFile("wb", suffix=".gp", delete=False) as tmp:
            tmp.write(synthetic)
            tmp_path = tmp.name
        try:
            workloads.append(
                _measure_workload(
                    label=f"synthetic_{num_specs}_specs",
                    path=tmp_path,
                    data=synthetic,
                    runs=runs,
                    warmup=warmup,
                )
            )
        finally:
            try:
                Path(tmp_path).unlink()
            except FileNotFoundError:
                pass

    report = {
        "tool": "bench_core_parse",
        "phase": "1E",
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
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--num-specs", type=int, default=200)
    parser.add_argument("--skip-synthetic", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write a JSON report to this path in addition to stdout.",
    )
    return parser


def test_bench_core_parse_smoke(tmp_path: Path) -> None:
    """Sanity check the harness on tiny inputs so a regression here is caught."""
    report = run_bench(
        runs=2,
        warmup=1,
        num_specs=4,
        output=tmp_path / "bench.json",
        skip_synthetic=False,
    )
    workloads = report["workloads"]
    assert len(workloads) == 2
    for w in workloads:
        assert "python_direct" in w["scenarios"]
        # Rust scenarios only present when the extension is importable; do
        # not assert availability either way so the smoke test passes on
        # both Rust-enabled and pure-Python machines.


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    run_bench(
        runs=args.runs,
        warmup=args.warmup,
        num_specs=args.num_specs,
        output=args.output,
        skip_synthetic=args.skip_synthetic,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
