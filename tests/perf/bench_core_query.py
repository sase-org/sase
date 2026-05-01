"""Benchmark sase query parse/evaluate paths across available backends.

Phase 2A (sase-17.1) of `plans/202604/rust_backend_phase2_query.md` captured
the optimized Python baseline before any Rust query backend landed. Phase 4 of
`plans/202604/query_batch_persistent_corpus.md` extended the same harness with
persistent-corpus rows so product routing could be gated against a Python batch
reference without confusing it with the known-regressed direct one-shot binding.

Scenarios (per workload):

- Python direct parse: :func:`sase.ace.query.parser._parse_query_python`.
- Python facade parse: :func:`sase.core.query_facade.parse_query` through the
  public facade.
- Python parse + evaluate: parse once, then evaluate against ``N`` specs
  using :func:`sase.core.query_facade.evaluate_query_with_context` with a
  context built once per workload (the optimized post-Phase-1 path).
- Rust one-shot diagnostic: ``sase_core_rs.evaluate_query_many(query, dicts)``
  with prebuilt wire dicts, kept only as a non-product comparison.
- Rust persistent corpus compile: product-visible
  :func:`sase.core.query_corpus_facade.compile_query_corpus` cost.
- Rust persistent fully compiled evaluation: corpus and query program compiled
  outside the timed loop, then ``evaluate_many(program, corpus)`` timed.
- Rust persistent query-keystroke path: corpus compiled outside the timed loop,
  then query compile plus evaluation timed through
  :func:`sase.core.query_corpus_facade.evaluate_query_many_with_corpus`.

Workloads:

- ``parse_only``: a single representative query — no specs needed.
- ``synthetic_<N>_specs`` for ``N`` in 100, 1000, 10000: the same query
  evaluated against generated specs from
  :func:`tests.perf.bench_core_parse._build_synthetic_bytes`. The specs are
  parsed once and reused so per-scenario timings reflect query work only.

Marked ``slow`` so it does not run in ``just test``. Run via::

    just bench-query
    just bench-query --runs 5 --query "status:Ready AND ancestor:spec_0"
    just bench-query --include-home-tree
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sase.ace.changespec.models import ChangeSpec  # noqa: E402
from sase.ace.query import evaluator as query_evaluator  # noqa: E402
from sase.ace.query.parser import _parse_query_python  # noqa: E402
from sase.core import parser_facade, query_corpus_facade, query_facade  # noqa: E402
from sase.core.wire import to_json_dict  # noqa: E402
from sase.core.wire_conversion import changespec_to_wire  # noqa: E402

from tests.perf.bench_core_parse import _build_synthetic_bytes  # noqa: E402, PLC2701


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


def _load_home_tree_specs() -> tuple[list[ChangeSpec], list[str]]:
    """Load real home-tree ChangeSpecs when available for an explicit local row."""
    projects_root = Path.home() / ".sase" / "projects"
    if not projects_root.exists():
        return [], [f"{projects_root} does not exist"]

    gp_files = sorted(projects_root.glob("*/*.gp"))
    if not gp_files:
        return [], [f"{projects_root} contains no project .gp files"]

    specs: list[ChangeSpec] = []
    notes: list[str] = []
    for path in gp_files:
        try:
            specs.extend(parser_facade.parse_project_file(str(path)))
        except Exception as exc:  # pragma: no cover - local fixture dependent
            notes.append(f"skipped {path.name}: {exc}")
    if not specs:
        notes.append("no ChangeSpecs parsed from home-tree .gp files")
    return specs, notes


def _measure_parse_only(
    *,
    query: str,
    runs: int,
    warmup: int,
) -> dict[str, Any]:
    def py_direct() -> int:
        return id(_parse_query_python(query))

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
    return _measure_query_workload(
        query=query,
        specs=_load_synthetic_specs(num_specs),
        label=f"synthetic_{num_specs}_specs",
        num_specs=num_specs,
        runs=runs,
        warmup=warmup,
    )


def _measure_query_workload(
    *,
    query: str,
    specs: list[ChangeSpec],
    label: str,
    num_specs: int,
    runs: int,
    warmup: int,
    notes: list[str] | None = None,
) -> dict[str, Any]:

    def py_direct_parse() -> int:
        return id(_parse_query_python(query))

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

    def py_batch_reference() -> int:
        expr = _parse_query_python(query)
        ctx = query_evaluator.build_query_context(specs)
        return sum(
            query_evaluator.evaluate_query_with_context(expr, cs, ctx) for cs in specs
        )

    scenarios: dict[str, dict[str, float]] = {
        "python_direct_parse": _time_calls(py_direct_parse, runs=runs, warmup=warmup),
        "python_facade_parse": _time_calls(py_facade_parse, runs=runs, warmup=warmup),
        "python_parse_and_evaluate": _time_calls(
            py_parse_and_eval, runs=runs, warmup=warmup
        ),
        "reference_python_batch_evaluate_many": _time_calls(
            py_batch_reference, runs=runs, warmup=warmup
        ),
    }

    rust_module = _load_rust_module()
    if rust_module is not None:
        spec_dicts = [to_json_dict(changespec_to_wire(cs)) for cs in specs]

        def rust_one_shot_diagnostic_eval() -> int:
            return sum(rust_module.evaluate_query_many(query, spec_dicts))

        scenarios["rust_one_shot_diagnostic_evaluate_many"] = _time_calls(
            rust_one_shot_diagnostic_eval, runs=runs, warmup=warmup
        )

        if all(
            hasattr(rust_module, name)
            for name in ("compile_corpus", "compile_query", "evaluate_many")
        ):

            def rust_corpus_compile() -> int:
                corpus = query_corpus_facade.compile_query_corpus(specs)
                return corpus.expected_length

            corpus = query_corpus_facade.compile_query_corpus(specs)
            direct_corpus = rust_module.compile_corpus(spec_dicts)
            direct_program = rust_module.compile_query(query)

            def rust_persistent_fully_compiled() -> int:
                return sum(rust_module.evaluate_many(direct_program, direct_corpus))

            def rust_persistent_query_keystroke() -> int:
                return sum(
                    query_corpus_facade.evaluate_query_many_with_corpus(query, corpus)
                )

            scenarios["rust_persistent_corpus_compile"] = _time_calls(
                rust_corpus_compile, runs=runs, warmup=warmup
            )
            scenarios["rust_persistent_fully_compiled_evaluate_many"] = _time_calls(
                rust_persistent_fully_compiled, runs=runs, warmup=warmup
            )
            scenarios["rust_persistent_query_keystroke_evaluate_many"] = _time_calls(
                rust_persistent_query_keystroke, runs=runs, warmup=warmup
            )

    return {
        "label": label,
        "query": query,
        "num_specs": num_specs,
        "scenarios": scenarios,
        "notes": list(notes or []),
    }


def _print_human(report: dict[str, Any]) -> None:
    print()
    label = report.get("label", "")
    if report.get("skipped"):
        print(f"# {label} [skipped]")
        print(f"  reason={report.get('skip_reason', 'not available')}")
        return
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
    include_home_tree: bool = False,
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

    home_tree_notes: list[str] = []
    if include_home_tree:
        home_specs, home_tree_notes = _load_home_tree_specs()
        if home_specs:
            workloads.append(
                _measure_query_workload(
                    query=query,
                    specs=home_specs,
                    label="home_tree",
                    num_specs=len(home_specs),
                    runs=runs,
                    warmup=warmup,
                    notes=home_tree_notes,
                )
            )
        else:
            workloads.append(
                {
                    "label": "home_tree",
                    "skipped": True,
                    "skip_reason": "; ".join(home_tree_notes)
                    or "home-tree fixture unavailable",
                }
            )
    else:
        workloads.append(
            {
                "label": "home_tree",
                "skipped": True,
                "skip_reason": "pass --include-home-tree for local-only home-tree measurement",
            }
        )

    report = {
        "tool": "bench_core_query",
        "phase": "query_corpus_phase4",
        "rust_available": _load_rust_module() is not None,
        "gate": _query_corpus_gate(workloads),
        "home_tree": {
            "requested": include_home_tree,
            "notes": home_tree_notes,
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


def _query_corpus_gate(workloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the Phase 4 routing gate from benchmark workload medians."""
    required = {
        "synthetic_100_specs": {"min_speedup": 1.0},
        "synthetic_1000_specs": {"min_speedup": 2.0},
        "synthetic_10000_specs": {"min_speedup": 2.0},
    }
    rows: dict[str, dict[str, Any]] = {}
    passed = True
    for workload in workloads:
        label = workload.get("label")
        if label not in required or workload.get("skipped"):
            continue
        scenarios = workload.get("scenarios", {})
        py = scenarios.get("reference_python_batch_evaluate_many", {}).get("median_ms")
        rust = scenarios.get("rust_persistent_query_keystroke_evaluate_many", {}).get(
            "median_ms"
        )
        speedup = None
        row_passed = False
        if py is not None and rust is not None and rust > 0.0:
            speedup = float(py) / float(rust)
            row_passed = speedup >= required[label]["min_speedup"]
        else:
            passed = False
        if not row_passed:
            passed = False
        rows[label] = {
            "python_batch_median_ms": py,
            "rust_persistent_query_keystroke_median_ms": rust,
            "speedup": speedup,
            "min_speedup": required[label]["min_speedup"],
            "passed": row_passed,
        }

    missing = [label for label in required if label not in rows]
    if missing:
        passed = False
    return {
        "name": "query_corpus_phase4_routing_gate",
        "passed": passed,
        "required_workloads": list(required),
        "missing_workloads": missing,
        "rows": rows,
    }


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
    home_group = parser.add_mutually_exclusive_group()
    home_group.add_argument(
        "--include-home-tree",
        dest="include_home_tree",
        action="store_true",
        default=None,
        help=(
            "Also benchmark the real ~/.sase/projects tree when present. "
            "This is the default outside CI."
        ),
    )
    home_group.add_argument(
        "--skip-home-tree",
        dest="include_home_tree",
        action="store_false",
        help="Skip the local-only ~/.sase/projects workload.",
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
    assert len(workloads) == 3
    parse_only = workloads[0]
    assert parse_only["label"] == "parse_only"
    assert "python_direct_parse" in parse_only["scenarios"]
    assert "python_facade_parse" in parse_only["scenarios"]
    eval_workload = workloads[1]
    assert eval_workload["num_specs"] == 8
    assert "python_parse_and_evaluate" in eval_workload["scenarios"]
    assert workloads[2]["label"] == "home_tree"
    assert workloads[2]["skipped"] is True


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    include_home_tree = (
        args.include_home_tree
        if args.include_home_tree is not None
        else not bool(os.environ.get("CI"))
    )
    run_bench(
        runs=args.runs,
        warmup=args.warmup,
        query=args.query,
        spec_sizes=args.spec_sizes,
        output=args.output,
        include_home_tree=include_home_tree,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
