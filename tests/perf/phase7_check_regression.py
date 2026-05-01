"""Phase 7E regression-floor checker (sase-1e.5).

Runs a stable subset of the Phase 7B core-operation benchmarks under
default Rust and explicit Python in one process, then compares the
measured medians against the floor recorded in
``tests/perf/baselines/phase7_regression_floor.json``.

Two checks per anchor:

- **Absolute floor** — current Rust median must not exceed
  ``rust_slowdown_factor * phase7b_rust_median_s``. This is the
  "must not regress further" guard and is hardware-dependent; the
  factor is set permissively to absorb runner variance.
- **Relative floor** — for anchors with ``must_beat_python: true``,
  current Rust median must be strictly less than current Python median.
  Both medians are timed in the same process on the same hardware, so
  this check is hardware-independent.

The script exits ``1`` if any anchor fails either check (or any anchor
scenario is missing). It always writes a JSON report (path overridable
via ``--report-path``) so CI can upload it on failure.

Local usage::

    just install
    just phase7-perf-check          # exits 0 if floor holds
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.perf.phase7.metadata import (  # noqa: E402
    PHASE7_ARTIFACT_DIR,
    BackendChoice,
    build_metadata,
)
from tests.perf.phase7.summary import scenario_median  # noqa: E402

DEFAULT_BASELINE_PATH = (
    REPO_ROOT / "tests" / "perf" / "baselines" / "phase7_regression_floor.json"
)
DEFAULT_REPORT_PATH = PHASE7_ARTIFACT_DIR / "rust_backend_phase7_floor_check.json"


# Harness identifiers used to group anchors. Phase 7B already has one
# adaptor per harness in run_phase7b.py — we reuse those instead of
# re-implementing the per-harness orchestration.
_HARNESS_FOR_SURFACE: Mapping[str, str] = {
    "parse_project_bytes": "core_parse",
    "parse_query": "core_query",
    "evaluate_query_many": "core_query",
    "scan_agent_artifacts": "agent_scan",
    "read_status_from_lines": "status_state_machine",
    "apply_status_update": "status_state_machine",
    "plan_status_transition": "status_state_machine",
    "notification_store": "notification_store",
}


@dataclass(frozen=True)
class _AnchorSpec:
    """One row from the baseline file (immutable input)."""

    anchor_id: str
    surface: str
    workload: str
    scenario: str
    phase7b_python_median_s: float
    phase7b_rust_median_s: float
    must_beat_python: bool
    rationale: str


@dataclass(frozen=True)
class AnchorResult:
    """Per-anchor outcome of the floor check."""

    spec: _AnchorSpec
    current_rust_median_s: float | None
    current_python_median_s: float | None
    rust_ceiling_s: float
    failures: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "anchor_id": self.spec.anchor_id,
            "surface": self.spec.surface,
            "workload": self.spec.workload,
            "scenario": self.spec.scenario,
            "must_beat_python": self.spec.must_beat_python,
            "phase7b_rust_median_s": self.spec.phase7b_rust_median_s,
            "phase7b_python_median_s": self.spec.phase7b_python_median_s,
            "current_rust_median_s": self.current_rust_median_s,
            "current_python_median_s": self.current_python_median_s,
            "rust_ceiling_s": self.rust_ceiling_s,
            "passed": self.passed,
            "failures": list(self.failures),
            "notes": list(self.notes),
        }


# ---- baseline loader -------------------------------------------------------


def load_baseline(path: Path) -> tuple[float, list[_AnchorSpec], dict[str, Any]]:
    """Read the baseline file and return (slowdown_factor, anchors, raw)."""
    raw = json.loads(path.read_text())
    if raw.get("schema_version") != 1:
        raise ValueError(
            f"Unsupported baseline schema_version "
            f"{raw.get('schema_version')!r} in {path}"
        )
    factor = float(raw["tolerance"]["rust_slowdown_factor"])
    anchors = [
        _AnchorSpec(
            anchor_id=a["id"],
            surface=a["surface"],
            workload=a["workload"],
            scenario=a["scenario"],
            phase7b_python_median_s=float(a["phase7b_python_median_s"]),
            phase7b_rust_median_s=float(a["phase7b_rust_median_s"]),
            must_beat_python=bool(a["must_beat_python"]),
            rationale=str(a.get("rationale", "")),
        )
        for a in raw["anchors"]
    ]
    return factor, anchors, raw


# ---- harness drivers -------------------------------------------------------


@dataclass(frozen=True)
class _HarnessConfig:
    """Per-harness sample sizes used by the floor check.

    The committed Phase 7B configuration is the gold standard; the floor
    check uses a slightly trimmed config so the in-CI cost stays bounded
    while keeping medians stable enough for the relative check.
    """

    core_parse: Mapping[str, Any]
    core_query: Mapping[str, Any]
    agent_scan: Mapping[str, Any]
    status_state_machine: Mapping[str, Any]
    notification_store: Mapping[str, Any]


_DEFAULT_CONFIG = _HarnessConfig(
    core_parse={"runs": 15, "warmup": 3, "num_specs": 200},
    core_query={"runs": 20, "warmup": 3, "spec_sizes": (100,)},
    agent_scan={
        "projects": 6,
        "per_project": 200,
        "workflow_fraction": 0.25,
        "runs": 8,
        "warmup": 2,
        "include_home": False,
    },
    status_state_machine={
        "runs": 200,
        "warmup": 20,
        "num_specs": 200,
        "transition_runs": 5,
    },
    notification_store={"runs": 3, "warmup": 1, "count": 5_000},
)

# Smoke runs keep the workload labels compatible with the committed
# anchors, but use fewer samples than the default CI-style floor.
_SMOKE_CONFIG = _HarnessConfig(
    core_parse={"runs": 3, "warmup": 1, "num_specs": 200},
    core_query={"runs": 3, "warmup": 1, "spec_sizes": (50,)},
    agent_scan={
        "projects": 6,
        "per_project": 200,
        "workflow_fraction": 0.25,
        "runs": 3,
        "warmup": 1,
        "include_home": False,
    },
    status_state_machine={
        "runs": 5,
        "warmup": 1,
        "num_specs": 20,
        "transition_runs": 2,
    },
    notification_store={"runs": 1, "warmup": 1, "count": 5_000},
)


def _config_for_anchors(
    cfg: _HarnessConfig, anchors: Sequence[_AnchorSpec]
) -> _HarnessConfig:
    """Augment harness sizes so newly anchored query workloads are produced.

    The historical floor only anchored ``parse_query.parse_only`` and kept the
    query harness cheap by timing one small synthetic evaluate workload. Phase 4
    exposes persistent-corpus evaluate rows at 100/1000/10000; if a later
    baseline adds any of those rows as anchors, the checker must run the
    matching sizes instead of silently missing the workload.
    """
    required_query_sizes = set(cfg.core_query.get("spec_sizes", ()))
    for anchor in anchors:
        if anchor.surface != "evaluate_query_many":
            continue
        prefix = "synthetic_"
        suffix = "_specs"
        if anchor.workload.startswith(prefix) and anchor.workload.endswith(suffix):
            value = anchor.workload[len(prefix) : -len(suffix)]
            try:
                required_query_sizes.add(int(value))
            except ValueError:
                continue

    core_query = dict(cfg.core_query)
    core_query["spec_sizes"] = tuple(sorted(required_query_sizes))
    return _HarnessConfig(
        core_parse=cfg.core_parse,
        core_query=core_query,
        agent_scan=cfg.agent_scan,
        status_state_machine=cfg.status_state_machine,
        notification_store=cfg.notification_store,
    )


def _run_required_harnesses(
    *, cfg: _HarnessConfig, harnesses: set[str]
) -> dict[str, dict[str, Any]]:
    """Run only the harnesses whose surfaces appear in ``harnesses``.

    Returns ``surface -> payload`` shaped exactly like
    :func:`tests.perf.phase7.run_phase7b` so the lookup logic below can
    treat both code paths identically.
    """
    from tests.perf.phase7.run_phase7b import (
        _bench_agent_scan,
        _bench_core_parse,
        _bench_core_query,
        _bench_status_state_machine,
    )

    by_surface: dict[str, dict[str, Any]] = {}

    if "core_parse" in harnesses:
        print("\n==== Phase 7E floor: bench_core_parse ====")
        by_surface.update(_bench_core_parse(**cfg.core_parse))
    if "core_query" in harnesses:
        print("\n==== Phase 7E floor: bench_core_query ====")
        by_surface.update(_bench_core_query(**cfg.core_query))
    if "agent_scan" in harnesses:
        print("\n==== Phase 7E floor: bench_agent_scan ====")
        by_surface.update(_bench_agent_scan(**cfg.agent_scan))
    if "status_state_machine" in harnesses:
        print("\n==== Phase 7E floor: bench_status_state_machine ====")
        by_surface.update(_bench_status_state_machine(**cfg.status_state_machine))
    if "notification_store" in harnesses:
        from tests.perf.bench_notification_store import run_phase7_floor_payload

        print("\n==== Phase 7 floor: bench_notification_store ====")
        by_surface.update(run_phase7_floor_payload(**cfg.notification_store))

    return by_surface


# ---- per-anchor evaluation -------------------------------------------------


def _find_workload(
    payload: Mapping[str, Any] | None, label: str
) -> Mapping[str, Any] | None:
    if not payload:
        return None
    for w in payload.get("workloads", []):
        if w.get("label") == label:
            return w
    return None


def _extract_medians(
    *,
    by_surface: Mapping[str, Mapping[str, Any]],
    spec: _AnchorSpec,
) -> tuple[float | None, float | None, list[str]]:
    """Return ``(rust_median_s, python_median_s, notes)`` for one anchor."""
    notes: list[str] = []
    payload = by_surface.get(spec.surface)
    if payload is None:
        notes.append(f"surface {spec.surface!r} not produced by any harness")
        return None, None, notes
    workload = _find_workload(payload, spec.workload)
    if workload is None:
        notes.append(
            f"workload {spec.workload!r} not present in surface {spec.surface!r}"
        )
        return None, None, notes
    baseline = workload.get("baseline") or {}
    candidate = workload.get("candidate") or {}
    py_summary = baseline.get(spec.scenario)
    rust_summary = candidate.get(spec.scenario)
    if not py_summary:
        notes.append(
            f"scenario {spec.scenario!r} missing from baseline (python) summaries"
        )
    if not rust_summary:
        notes.append(
            f"scenario {spec.scenario!r} missing from candidate (rust) summaries"
        )
    py_med = scenario_median(py_summary) if py_summary else None
    rust_med = scenario_median(rust_summary) if rust_summary else None
    return rust_med, py_med, notes


def _check_anchor(
    *,
    spec: _AnchorSpec,
    rust_med: float | None,
    py_med: float | None,
    rust_slowdown_factor: float,
    notes: list[str],
) -> AnchorResult:
    rust_ceiling = spec.phase7b_rust_median_s * rust_slowdown_factor
    failures: list[str] = []

    if rust_med is None:
        failures.append("rust median unavailable (scenario missing or count=0)")
    elif rust_med > rust_ceiling:
        failures.append(
            f"absolute floor: rust median {rust_med * 1e6:.2f}us "
            f"exceeds ceiling {rust_ceiling * 1e6:.2f}us "
            f"(={rust_slowdown_factor:.2f}x phase7b rust median "
            f"{spec.phase7b_rust_median_s * 1e6:.2f}us)"
        )

    if spec.must_beat_python:
        if py_med is None:
            failures.append("must_beat_python: python median unavailable for this run")
        elif rust_med is not None and rust_med >= py_med:
            failures.append(
                f"must_beat_python: rust median {rust_med * 1e6:.2f}us "
                f">= python median {py_med * 1e6:.2f}us"
            )

    return AnchorResult(
        spec=spec,
        current_rust_median_s=rust_med,
        current_python_median_s=py_med,
        rust_ceiling_s=rust_ceiling,
        failures=tuple(failures),
        notes=tuple(notes),
    )


# ---- public entry point ----------------------------------------------------


def run_floor_check(
    *,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    smoke: bool = False,
) -> tuple[bool, dict[str, Any], list[AnchorResult]]:
    """Run the regression floor and return (ok, report, results)."""
    factor, anchors, raw_baseline = load_baseline(baseline_path)
    cfg = _config_for_anchors(_SMOKE_CONFIG if smoke else _DEFAULT_CONFIG, anchors)
    harnesses_needed = {
        _HARNESS_FOR_SURFACE[a.surface]
        for a in anchors
        if a.surface in _HARNESS_FOR_SURFACE
    }
    unknown = {a.surface for a in anchors if a.surface not in _HARNESS_FOR_SURFACE}
    if unknown:
        raise ValueError(
            f"Phase 7E checker has no harness mapping for surface(s): {sorted(unknown)}"
        )

    by_surface = _run_required_harnesses(cfg=cfg, harnesses=harnesses_needed)

    results: list[AnchorResult] = []
    for spec in anchors:
        rust_med, py_med, notes = _extract_medians(by_surface=by_surface, spec=spec)
        results.append(
            _check_anchor(
                spec=spec,
                rust_med=rust_med,
                py_med=py_med,
                rust_slowdown_factor=factor,
                notes=notes,
            )
        )

    metadata = build_metadata(
        tool="phase7_check_regression",
        surface="phase7_floor_check",
        workload="anchor_subset",
        backend=BackendChoice("summary"),
        runs=0,
        warmup=0,
        extra={
            "rust_slowdown_factor": factor,
            "smoke": smoke,
            "anchor_count": len(anchors),
        },
    )

    ok = all(r.passed for r in results)
    report = {
        "metadata": metadata.as_dict(),
        "baseline": {
            "path": str(baseline_path),
            "captured_at_phase": raw_baseline.get("captured_at_phase"),
            "git_sha_at_capture": raw_baseline.get("git_sha_at_capture"),
            "rust_slowdown_factor": factor,
        },
        "ok": ok,
        "results": [r.as_dict() for r in results],
    }
    return ok, report, results


# ---- CLI -------------------------------------------------------------------


def _print_results(results: Sequence[AnchorResult], factor: float) -> None:
    print("\n==== Phase 7E floor check results ====")
    print(f"  rust_slowdown_factor = {factor:.2f}x phase7b rust median")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        rust_us = (
            f"{r.current_rust_median_s * 1e6:.2f}us"
            if r.current_rust_median_s is not None
            else "n/a"
        )
        py_us = (
            f"{r.current_python_median_s * 1e6:.2f}us"
            if r.current_python_median_s is not None
            else "n/a"
        )
        ceil_us = f"{r.rust_ceiling_s * 1e6:.2f}us"
        print(
            f"  [{status}] {r.spec.anchor_id}: rust={rust_us} "
            f"python={py_us} ceiling={ceil_us} "
            f"must_beat_python={r.spec.must_beat_python}"
        )
        for note in r.notes:
            print(f"        note: {note}")
        for failure in r.failures:
            print(f"        FAIL: {failure}")


def _argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument(
        "-b",
        "--baseline-path",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help="Path to the baseline JSON (default: tests/perf/baselines/phase7_regression_floor.json)",
    )
    p.add_argument(
        "-r",
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=(
            "Where to write the JSON floor-check report. "
            f"Default: {DEFAULT_REPORT_PATH} (relative to the repo root)."
        ),
    )
    p.add_argument(
        "-s",
        "--smoke",
        action="store_true",
        help=(
            "Run with tiny sample sizes (fast). The relative must-beat-python "
            "check still works; the absolute floor check is informational only "
            "because medians are too noisy at this size."
        ),
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress the per-anchor result table on stdout.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    ok, report, results = run_floor_check(
        baseline_path=args.baseline_path,
        smoke=args.smoke,
    )

    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n")

    if not args.quiet:
        factor = float(report["baseline"]["rust_slowdown_factor"])
        _print_results(results, factor)
        print(f"\n  report written to {args.report_path}")

    if not ok:
        print("\nPhase 7E floor check FAILED.", file=sys.stderr)
        return 1
    print("\nPhase 7E floor check passed.")
    return 0


if __name__ == "__main__":
    # The Phase 7B harness layer expects to import from the repo root —
    # set ``PYTHONUNBUFFERED`` only when running from the CLI so the
    # progress prints appear in CI logs in real time.
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    sys.exit(main())
