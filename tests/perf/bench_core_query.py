"""Benchmark sase query parse/evaluate paths across available backends.

Phase 2A (sase-17.1) of `plans/202604/rust_backend_phase2_query.md`. Measures
the optimized Python baseline before any Rust query backend lands so Phase 2F
has a real number to gate against.

Scenarios (per workload):

- Python direct parse: :func:`sase.ace.query.parser.parse_query_python`.
- Python facade parse: :func:`sase.core.query_facade.parse_query` with the
  default Python backend.
- Python parse + evaluate: parse once, then evaluate against ``N`` specs
  using :func:`sase.core.query_facade.evaluate_query_with_context` with a
  context built once per workload (the optimized post-Phase-1 path).
- Rust direct / Rust facade / dual-run: only added once Phase 2D's binding
  exists. Phase 2A leaves slots for them so the harness shape doesn't churn.

Workloads:

- ``parse_only``: a single representative query — no specs needed.
- ``synthetic_<N>_specs`` for ``N`` in 100, 1000, 10000: the same query
  evaluated against generated specs from
  :func:`tests.perf.bench_core_parse._build_synthetic_bytes`. The specs are
  parsed once and reused so per-scenario timings reflect query work only.

Marked ``slow`` so it does not run in ``just test``. Run via::

    just bench-query
    just bench-query --runs 5 --query "status:Ready AND ancestor:spec_0"
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

import pytest

from sase.ace.changespec.models import ChangeSpec
from sase.ace.query.parser import parse_query_python
from sase.core import parser_facade, query_facade
from sase.core.wire import to_json_dict
from sase.core.wire_conversion import changespec_to_wire

from tests.perf.bench_core_parse import _build_synthetic_bytes  # noqa: PLC2701


def _load_rust_module() -> Any | None:
    import importlib.util as _u

    if _u.find_spec("sase_core_rs") is None:
        return None
    import importlib

    return importlib.import_module("sase_core_rs")


pytestmark = pytest.mark.slow

DEFAULT_QUERY = '"feature" OR status:Ready'
DEFAULT_SPEC_SIZES = (100, 1_000, 10_000)


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


def _load_synthetic_specs(num_specs: int) -> list[ChangeSpec]:
    """Materialize ``num_specs`` synthetic specs from the parse benchmark.

    We parse through the public facade so the wire shape used by query
    evaluation is identical to what production code sees.
    """
    data = _build_synthetic_bytes(num_specs)
    with tempfile.NamedTemporaryFile("wb", suffix=".gp", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return parser_facade.parse_project_file(tmp_path)
    finally:
        try:
            Path(tmp_path).unlink()
        except FileNotFoundError:
            pass


def _measure_parse_only(
    *,
    query: str,
    runs: int,
    warmup: int,
) -> dict[str, Any]:
    def py_direct() -> int:
        return id(parse_query_python(query))

    def py_facade() -> int:
        return id(query_facade.parse_query(query))

    scenarios: dict[str, dict[str, float]] = {
        "python_direct_parse": _time_calls(py_direct, runs=runs, warmup=warmup),
        "python_facade_parse": _time_calls(py_facade, runs=runs, warmup=warmup),
    }

    rust_module = _load_rust_module()
    if rust_module is not None:

        def rust_direct() -> int:
            return id(rust_module.parse_query(query))

        def rust_facade() -> int:
            return id(query_facade.parse_query(query))

        scenarios["rust_direct_parse"] = _time_calls(
            rust_direct, runs=runs, warmup=warmup
        )
        scenarios["rust_facade_parse"] = _time_calls(
            rust_facade, runs=runs, warmup=warmup
        )

    return {
        "label": "parse_only",
        "query": query,
        "scenarios": scenarios,
    }


def _measure_parse_evaluate(
    *,
    query: str,
    num_specs: int,
    runs: int,
    warmup: int,
) -> dict[str, Any]:
    specs = _load_synthetic_specs(num_specs)

    def py_direct_parse() -> int:
        return id(parse_query_python(query))

    def py_facade_parse() -> int:
        return id(query_facade.parse_query(query))

    def py_parse_and_eval() -> int:
        # The hot path post-Phase-1: parse once per refresh, build the
        # context once, evaluate every spec.
        expr = query_facade.parse_query(query)
        ctx = query_facade.build_query_context(specs)
        hits = 0
        for cs in specs:
            if query_facade.evaluate_query_with_context(expr, cs, ctx):
                hits += 1
        return hits

    def py_batch() -> int:
        return sum(query_facade._evaluate_query_many_python(query, specs))

    scenarios: dict[str, dict[str, float]] = {
        "python_direct_parse": _time_calls(py_direct_parse, runs=runs, warmup=warmup),
        "python_facade_parse": _time_calls(py_facade_parse, runs=runs, warmup=warmup),
        "python_parse_and_evaluate": _time_calls(
            py_parse_and_eval, runs=runs, warmup=warmup
        ),
        "python_batch_evaluate_many": _time_calls(py_batch, runs=runs, warmup=warmup),
    }

    rust_module = _load_rust_module()
    if rust_module is not None:
        spec_dicts = [to_json_dict(changespec_to_wire(cs)) for cs in specs]

        def rust_direct_eval() -> int:
            return sum(rust_module.evaluate_query_many(query, spec_dicts))

        def rust_facade_eval() -> int:
            return sum(query_facade.evaluate_query_many(query, specs))

        scenarios["rust_direct_evaluate_many"] = _time_calls(
            rust_direct_eval, runs=runs, warmup=warmup
        )
        scenarios["rust_facade_evaluate_many"] = _time_calls(
            rust_facade_eval, runs=runs, warmup=warmup
        )

    return {
        "label": f"synthetic_{num_specs}_specs",
        "query": query,
        "num_specs": num_specs,
        "scenarios": scenarios,
    }


def _print_human(report: dict[str, Any]) -> None:
    print()
    label = report.get("label", "")
    extra = ""
    if "num_specs" in report:
        extra = f" ({report['num_specs']} specs)"
    print(f"# {label}{extra}")
    print(f"  query={report.get('query')!r}")
    header = (
        f"{'scenario':<28} {'min_ms':>10} {'median_ms':>12} "
        f"{'p95_ms':>10} {'max_ms':>10}"
    )
    print("  " + header)
    print("  " + "-" * len(header))
    for name, summary in report["scenarios"].items():
        if summary.get("count", 0) == 0:
            continue
        print(
            "  " + f"{name:<28} {summary['min_ms']:>10.3f} "
            f"{summary['median_ms']:>12.3f} {summary['p95_ms']:>10.3f} "
            f"{summary['max_ms']:>10.3f}"
        )


def run_bench(
    *,
    runs: int,
    warmup: int,
    query: str,
    spec_sizes: tuple[int, ...],
    output: Path | None,
) -> dict[str, Any]:
    workloads: list[dict[str, Any]] = []

    workloads.append(_measure_parse_only(query=query, runs=runs, warmup=warmup))
    for size in spec_sizes:
        workloads.append(
            _measure_parse_evaluate(
                query=query,
                num_specs=size,
                runs=runs,
                warmup=warmup,
            )
        )

    report = {
        "tool": "bench_core_query",
        "phase": "2F",
        "rust_available": _load_rust_module() is not None,
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
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument(
        "--spec-sizes",
        type=lambda s: tuple(int(x) for x in s.split(",") if x.strip()),
        default=DEFAULT_SPEC_SIZES,
        help="Comma-separated spec list sizes (default: 100,1000,10000).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write a JSON report to this path in addition to stdout.",
    )
    return parser


def test_bench_core_query_smoke(tmp_path: Path) -> None:
    """Sanity check the harness on tiny inputs so a regression here is caught."""
    report = run_bench(
        runs=2,
        warmup=1,
        query=DEFAULT_QUERY,
        spec_sizes=(8,),
        output=tmp_path / "bench.json",
    )
    workloads = report["workloads"]
    assert len(workloads) == 2
    parse_only = workloads[0]
    assert parse_only["label"] == "parse_only"
    assert "python_direct_parse" in parse_only["scenarios"]
    assert "python_facade_parse" in parse_only["scenarios"]
    eval_workload = workloads[1]
    assert eval_workload["num_specs"] == 8
    assert "python_parse_and_evaluate" in eval_workload["scenarios"]


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    run_bench(
        runs=args.runs,
        warmup=args.warmup,
        query=args.query,
        spec_sizes=args.spec_sizes,
        output=args.output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
