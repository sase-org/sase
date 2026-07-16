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

Absolute-only notification anchors use five-sample medians and receive at
most one confirmation measurement when the initial median exceeds its
ceiling. This distinguishes a sustained regression from isolated hosted-runner
contention without retrying the same-process ``must_beat_python`` checks.

Local usage::

    just install
    just phase7-perf-check          # exits 0 if floor holds
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
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
from tests.perf.phase7.regression_floor import (  # noqa: E402
    AnchorResult,
    _AnchorSpec,
    _apply_notification_confirmation,
    _check_anchor,
    _extract_medians,
    _needs_notification_confirmation,
    load_baseline,
)
from tests.perf.phase7.regression_harness import (  # noqa: E402
    _DEFAULT_CONFIG,
    _HARNESS_FOR_SURFACE,
    _SMOKE_CONFIG,
    _config_for_anchors,
    _run_required_harnesses,
)

DEFAULT_BASELINE_PATH = (
    REPO_ROOT / "tests" / "perf" / "baselines" / "phase7_regression_floor.json"
)
DEFAULT_REPORT_PATH = PHASE7_ARTIFACT_DIR / "rust_backend_phase7_floor_check.json"


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

    # A single additional notification harness run confirms every eligible
    # initial failure together. The confirmation is therefore bounded even if
    # several notification anchors encounter the same whole-run contention.
    confirmation_anchor_ids = [
        result.spec.anchor_id
        for result in results
        if _needs_notification_confirmation(result)
    ]
    if confirmation_anchor_ids:
        print("\n==== Phase 7 floor: confirm absolute notification failures ====")
        confirmation_by_surface = _run_required_harnesses(
            cfg=cfg,
            harnesses={"notification_store"},
        )
        confirmed_results: list[AnchorResult] = []
        for result in results:
            if not _needs_notification_confirmation(result):
                confirmed_results.append(result)
                continue
            rust_med, _py_med, notes = _extract_medians(
                by_surface=confirmation_by_surface,
                spec=result.spec,
            )
            confirmed_results.append(
                _apply_notification_confirmation(
                    result,
                    confirmation_rust_med=rust_med,
                    confirmation_notes=notes,
                )
            )
        results = confirmed_results

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
            "notification_sampling_runs": int(cfg.notification_store.get("runs", 0)),
            "notification_confirmation_count": len(confirmation_anchor_ids),
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
        "notification_confirmation": {
            "performed": bool(confirmation_anchor_ids),
            "anchor_ids": confirmation_anchor_ids,
            "sampling_runs": int(cfg.notification_store.get("runs", 0)),
            "max_additional_harness_runs": 1,
        },
        "ok": ok,
        "results": [r.as_dict() for r in results],
    }
    return ok, report, results


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
        confirmation = (
            f" confirmation={r.confirmation_rust_median_s * 1e6:.2f}us"
            if r.confirmation_performed and r.confirmation_rust_median_s is not None
            else " confirmation=n/a"
            if r.confirmation_performed
            else ""
        )
        print(
            f"  [{status}] {r.spec.anchor_id}: rust={rust_us} "
            f"python={py_us} ceiling={ceil_us}{confirmation} "
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
