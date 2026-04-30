"""Phase 7B driver: produce per-surface summary artifacts for shipped Rust ops.

Phase 7B (sase-1e.2) of `plans/202604/rust_backend_phase7.md`. Runs each
existing core-operation benchmark in-process, then writes one
``rust_backend_phase7_<surface>_summary.json`` artifact per shipped Rust
core operation under ``plans/202604/perf_artifacts/``. Each summary
embeds the Phase 7A metadata envelope (see :mod:`tests.perf.phase7`),
the relevant scenario summaries from the harness it was derived from,
and the per-(workload, scenario) ``ScenarioComparison`` rows produced by
:func:`tests.perf.phase7.summarize_report`.

Driving every surface from one script means Phase 7D/7E only have to
read a single deterministic artifact per surface to build their tables
and regression-floor checker, instead of reverse-engineering five
benchmark JSON shapes.

Usage::

    just install
    .venv/bin/python tests/perf/phase7/run_phase7b.py

Or pass ``--smoke`` to run quick configurations suitable for smoke-test
verification (artifacts will still be written but with tiny sample
sizes and a ``smoke=True`` flag baked into the metadata's ``extra``
field). The committed Phase 7B artifacts must be produced via the full
configuration so the medians are stable.

The per-harness adaptors live in :mod:`tests.perf.phase7.phase7b_adaptors`
and the artifact writer + git-workloads merger in
:mod:`tests.perf.phase7.phase7b_summary`. They are re-exported here for
back-compat with callers that still import ``_bench_*`` from this module
(notably :mod:`tests.perf.phase7_check_regression`).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
# Allow ``python tests/perf/phase7/run_phase7b.py`` (no ``-m``) so the
# script behaves like the other ``tests/perf/bench_*.py`` harnesses.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.perf.phase7.metadata import PHASE7_ARTIFACT_DIR  # noqa: E402
from tests.perf.phase7.phase7b_adaptors import (  # noqa: E402,F401
    _bench_agent_scan,
    _bench_core_parse,
    _bench_core_query,
    _bench_git_query_ops,
    _bench_status_state_machine,
)
from tests.perf.phase7.phase7b_summary import (  # noqa: E402
    _merge_git_workloads,
    _write_summary_artifact,
)


def run_phase7b(
    *,
    smoke: bool,
    artifact_dir: Path,
    include_home: bool,
    skip_git_e2e: bool,
) -> list[Path]:
    """Run every Phase 7B benchmark and write summary artifacts.

    Returns the list of artifact paths written.
    """
    cfg: dict[str, dict[str, Any]]
    if smoke:
        # Tiny configuration — used by the unit-test smoke and by ad-hoc
        # local runs. Committed artifacts must use the full configuration.
        cfg = {
            "core_parse": {"runs": 3, "warmup": 1, "num_specs": 20},
            "core_query": {"runs": 3, "warmup": 1, "spec_sizes": (50,)},
            "agent_scan": {
                "projects": 2,
                "per_project": 5,
                "workflow_fraction": 0.5,
                "runs": 3,
                "warmup": 1,
            },
            "status_state_machine": {
                "runs": 5,
                "warmup": 1,
                "num_specs": 20,
                "transition_runs": 3,
            },
            "git_query_ops": {
                "runs": 5,
                "warmup": 1,
                "small": 25,
                "medium": 200,
                "large": 1000,
                "e2e_runs": 3,
                "skip_e2e": skip_git_e2e,
            },
        }
    else:
        # Plan §7B "Work" recommended sample sizes.
        cfg = {
            "core_parse": {"runs": 20, "warmup": 3, "num_specs": 200},
            "core_query": {
                "runs": 20,
                "warmup": 3,
                "spec_sizes": (100, 1000, 10000),
            },
            "agent_scan": {
                "projects": 6,
                "per_project": 200,
                "workflow_fraction": 0.25,
                "runs": 10,
                "warmup": 2,
            },
            "status_state_machine": {
                "runs": 200,
                "warmup": 20,
                "num_specs": 200,
                "transition_runs": 20,
            },
            "git_query_ops": {
                "runs": 200,
                "warmup": 20,
                "small": 50,
                "medium": 1000,
                "large": 10000,
                "e2e_runs": None,
                "skip_e2e": skip_git_e2e,
            },
        }

    extra_common = {"smoke": smoke} if smoke else {}

    # All harnesses now go through direct-Rust facades; one in-process
    # pass per harness is sufficient.
    by_surface: dict[str, dict[str, Any]] = {}

    print("\n==== Phase 7B: parser core (bench_core_parse) ====")
    by_surface.update(_bench_core_parse(**cfg["core_parse"]))

    print("\n==== Phase 7B: query core (bench_core_query) ====")
    by_surface.update(_bench_core_query(**cfg["core_query"]))

    print("\n==== Phase 7B: agent scan (bench_agent_scan) ====")
    by_surface.update(_bench_agent_scan(**cfg["agent_scan"], include_home=include_home))

    print("\n==== Phase 7B: status state machine (bench_status_state_machine) ====")
    by_surface.update(_bench_status_state_machine(**cfg["status_state_machine"]))

    print("\n==== Phase 7B: git query ops (bench_git_query_ops) ====")
    rust_run = _bench_git_query_ops(
        **cfg["git_query_ops"], backend_label="default_rust"
    )
    by_surface.update(_merge_git_workloads(rust_run=rust_run))

    # Finally write a summary artifact per surface.
    written: list[Path] = []
    for surface, payload in by_surface.items():
        merged_extra = dict(payload.get("extra", {}))
        merged_extra.update(extra_common)
        path = _write_summary_artifact(
            surface=surface,
            tool=payload["tool"],
            workloads=payload["workloads"],
            runs=cfg_runs_for(surface, cfg),
            warmup=cfg_warmup_for(surface, cfg),
            extra=merged_extra,
            artifact_dir=artifact_dir,
        )
        written.append(path)
        print(f"  wrote {path}")

    return written


def cfg_runs_for(surface: str, cfg: Mapping[str, Mapping[str, Any]]) -> int:
    if surface == "parse_project_bytes":
        return int(cfg["core_parse"]["runs"])
    if surface in {"parse_query", "evaluate_query_many"}:
        return int(cfg["core_query"]["runs"])
    if surface == "scan_agent_artifacts":
        return int(cfg["agent_scan"]["runs"])
    if surface in {
        "read_status_from_lines",
        "apply_status_update",
        "plan_status_transition",
    }:
        return int(cfg["status_state_machine"]["runs"])
    return int(cfg["git_query_ops"]["runs"])


def cfg_warmup_for(surface: str, cfg: Mapping[str, Mapping[str, Any]]) -> int:
    if surface == "parse_project_bytes":
        return int(cfg["core_parse"]["warmup"])
    if surface in {"parse_query", "evaluate_query_many"}:
        return int(cfg["core_query"]["warmup"])
    if surface == "scan_agent_artifacts":
        return int(cfg["agent_scan"]["warmup"])
    if surface in {
        "read_status_from_lines",
        "apply_status_update",
        "plan_status_transition",
    }:
        return int(cfg["status_state_machine"]["warmup"])
    return int(cfg["git_query_ops"]["warmup"])


def _argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0] if __doc__ else "",
    )
    parser.add_argument(
        "-s",
        "--smoke",
        action="store_true",
        help=(
            "Run with tiny sample sizes (fast). Artifacts are still "
            "written but flagged with smoke=True in metadata.extra so "
            "they cannot be confused with real Phase 7B captures."
        ),
    )
    parser.add_argument(
        "-d",
        "--artifact-dir",
        type=Path,
        default=PHASE7_ARTIFACT_DIR,
        help="Override the artifact output directory.",
    )
    parser.add_argument(
        "-H",
        "--include-home",
        action="store_true",
        help=(
            "Also benchmark the real ~/.sase/projects tree in the "
            "agent_scan run (non-hermetic; off by default)."
        ),
    )
    parser.add_argument(
        "-G",
        "--skip-git-e2e",
        action="store_true",
        help=(
            "Skip the end-to-end git scenarios in bench_git_query_ops. "
            "Default behavior runs them when git is available."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    written = run_phase7b(
        smoke=args.smoke,
        artifact_dir=args.artifact_dir,
        include_home=args.include_home,
        skip_git_e2e=args.skip_git_e2e,
    )
    print(f"\nPhase 7B wrote {len(written)} summary artifact(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
