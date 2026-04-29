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
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
# Allow ``python tests/perf/phase7/run_phase7b.py`` (no ``-m``) so the
# script behaves like the other ``tests/perf/bench_*.py`` harnesses.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.perf.phase7.metadata import (  # noqa: E402
    PHASE7_ARTIFACT_DIR,
    BackendChoice,
    artifact_path,
    build_metadata,
)
from tests.perf.phase7.summary import summarize_report  # noqa: E402


# ---- per-harness adaptors --------------------------------------------------
#
# Each adaptor returns a dict mapping "surface" -> {
#   "tool": str,
#   "extra": dict,        # surface-specific metadata to merge into envelope
#   "workloads": [{
#       "label": str,
#       "size": dict,     # any size hints (size_bytes, num_specs, etc.)
#       "baseline": dict[scenario_name -> summary],
#       "candidate": dict[scenario_name -> summary],
#   }, ...],
# }


def _bench_core_parse(*, runs: int, warmup: int, num_specs: int) -> dict[str, Any]:
    from tests.perf.bench_core_parse import run_bench

    raw = run_bench(
        runs=runs,
        warmup=warmup,
        num_specs=num_specs,
        output=None,
        skip_synthetic=False,
    )
    workloads: list[dict[str, Any]] = []
    for w in raw["workloads"]:
        scenarios = w["scenarios"]
        py = {
            "python_direct": scenarios.get("python_direct", {}),
            "python_facade": scenarios.get("python_facade", {}),
        }
        rust = {
            # `rust_direct` and `rust_facade` only exist when the extension
            # is importable, but the harness leaves them out entirely
            # rather than emitting count=0 rows. Use ``.get`` so missing
            # rows degrade to ``None`` in the comparison.
            "rust_direct": scenarios.get("rust_direct", {}),
            "rust_facade": scenarios.get("rust_facade", {}),
        }
        # Pair python_facade <-> rust_facade and python_direct <-> rust_direct
        # for the comparison so each "scenario" name in the summary is the
        # backend-agnostic operation tier.
        baseline = {
            "facade": scenarios.get("python_facade", {}),
            "direct": scenarios.get("python_direct", {}),
        }
        candidate = {
            "facade": scenarios.get("rust_facade", {}),
            "direct": scenarios.get("rust_direct", {}),
        }
        workloads.append(
            {
                "label": w["label"],
                "size": {
                    "size_bytes": w.get("size_bytes"),
                    "runs": w.get("runs"),
                    "warmup": w.get("warmup"),
                },
                "baseline": baseline,
                "candidate": candidate,
                "raw_python_scenarios": py,
                "raw_rust_scenarios": rust,
            }
        )
    return {
        "parse_project_bytes": {
            "tool": "bench_core_parse",
            "extra": {"num_specs": num_specs},
            "workloads": workloads,
        }
    }


def _bench_core_query(
    *, runs: int, warmup: int, spec_sizes: tuple[int, ...]
) -> dict[str, Any]:
    from tests.perf.bench_core_query import DEFAULT_QUERY, run_bench

    raw = run_bench(
        runs=runs,
        warmup=warmup,
        query=DEFAULT_QUERY,
        spec_sizes=spec_sizes,
        output=None,
    )

    parse_workloads: list[dict[str, Any]] = []
    eval_workloads: list[dict[str, Any]] = []
    for w in raw["workloads"]:
        scenarios = w["scenarios"]
        # `parse_query` covers parse_only + every evaluate workload (because
        # each evaluate workload also re-times parse-only inside it).
        parse_workloads.append(
            {
                "label": w["label"],
                "size": {
                    "num_specs": w.get("num_specs"),
                    "query": w.get("query"),
                },
                "baseline": {
                    "facade": scenarios.get("python_facade_parse", {}),
                    "direct": scenarios.get("python_direct_parse", {}),
                },
                "candidate": {
                    "facade": scenarios.get("rust_facade_parse", {}),
                    "direct": scenarios.get("rust_direct_parse", {}),
                },
            }
        )
        # `evaluate_query_many` only appears once we have specs to evaluate
        # against; skip the parse_only workload here.
        if "rust_facade_evaluate_many" in scenarios or w.get("num_specs"):
            eval_workloads.append(
                {
                    "label": w["label"],
                    "size": {
                        "num_specs": w.get("num_specs"),
                        "query": w.get("query"),
                    },
                    "baseline": {
                        "facade": scenarios.get("python_batch_evaluate_many", {}),
                        "parse_and_evaluate": scenarios.get(
                            "python_parse_and_evaluate", {}
                        ),
                    },
                    "candidate": {
                        "facade": scenarios.get("rust_facade_evaluate_many", {}),
                        "direct": scenarios.get("rust_direct_evaluate_many", {}),
                    },
                }
            )
    return {
        "parse_query": {
            "tool": "bench_core_query",
            "extra": {"spec_sizes": list(spec_sizes)},
            "workloads": parse_workloads,
        },
        "evaluate_query_many": {
            "tool": "bench_core_query",
            "extra": {"spec_sizes": list(spec_sizes)},
            "workloads": eval_workloads,
        },
    }


def _bench_agent_scan(
    *,
    projects: int,
    per_project: int,
    workflow_fraction: float,
    runs: int,
    warmup: int,
    include_home: bool,
) -> dict[str, Any]:
    from tests.perf.bench_agent_scan import run_bench

    raw = run_bench(
        projects=projects,
        per_project=per_project,
        workflow_fraction=workflow_fraction,
        runs=runs,
        warmup=warmup,
        output=None,
        include_home=include_home,
    )
    workloads: list[dict[str, Any]] = []
    for w in raw["workloads"]:
        scenarios = w["scenarios"]
        workloads.append(
            {
                "label": w["label"],
                "size": {
                    "projects_root": w.get("projects_root"),
                    "target_name": w.get("target_name"),
                    "workflow_name": w.get("workflow_name"),
                },
                "baseline": {
                    "scan_facade": scenarios.get("scan_python_facade", {}),
                    "scan_facade_no_prompt_steps": scenarios.get(
                        "scan_python_facade_no_prompt_steps", {}
                    ),
                },
                "candidate": {
                    "scan_facade": scenarios.get("scan_rust_facade", {}),
                    "scan_rust_to_dict": scenarios.get("scan_rust_to_dict", {}),
                    "scan_rust_dict_to_wire": scenarios.get(
                        "scan_rust_dict_to_wire", {}
                    ),
                },
            }
        )
    return {
        "scan_agent_artifacts": {
            "tool": "bench_agent_scan",
            "extra": {
                "projects": projects,
                "per_project": per_project,
                "workflow_fraction": workflow_fraction,
                "include_home": include_home,
            },
            "workloads": workloads,
        }
    }


_STATUS_PURE_SURFACES = ("read_status_from_lines", "apply_status_update")
_STATUS_PLAN_SURFACE = "plan_status_transition"


def _bench_status_state_machine(
    *, runs: int, warmup: int, num_specs: int, transition_runs: int
) -> dict[str, Any]:
    from tests.perf.bench_status_state_machine import run_bench

    raw = run_bench(
        runs=runs,
        warmup=warmup,
        num_specs=num_specs,
        output=None,
        skip_synthetic=False,
        transition_runs=transition_runs,
    )

    out: dict[str, Any] = {
        surface: {
            "tool": "bench_status_state_machine",
            "extra": {"num_specs": num_specs},
            "workloads": [],
        }
        for surface in (*_STATUS_PURE_SURFACES, _STATUS_PLAN_SURFACE)
    }
    for w in raw["workloads"]:
        py = w.get("scenarios_python_backend", {})
        rust = w.get("scenarios_rust_backend", {})
        # Pure-helper workloads carry the shipped scenarios; transition
        # workloads do not, so skip them — they belong to the higher-level
        # orchestrator, not to the shipped Rust core ops covered here.
        if not py or "read_status_from_lines" not in py:
            continue
        size = {
            "size_bytes": w.get("size_bytes"),
            "lines": w.get("lines"),
            "target_name": w.get("target_name"),
        }
        for surface in (*_STATUS_PURE_SURFACES, _STATUS_PLAN_SURFACE):
            out[surface]["workloads"].append(
                {
                    "label": w["label"],
                    "size": size,
                    "baseline": {surface: py.get(surface, {})},
                    "candidate": {surface: rust.get(surface, {})},
                }
            )
    return out


_GIT_NORMALIZER_SCENARIO_TO_SURFACE = {
    "parse_git_branch_name_x4": "parse_git_branch_name",
    "derive_git_workspace_name_x5": "derive_git_workspace_name",
    "parse_git_conflicted_files_50": "parse_git_conflicted_files",
    "parse_git_local_changes_150": "parse_git_local_changes",
}


def _bench_git_query_ops(
    *,
    runs: int,
    warmup: int,
    small: int,
    medium: int,
    large: int,
    e2e_runs: int | None,
    skip_e2e: bool,
    backend_label: str,
) -> dict[str, Any]:
    """Run the Git query ops benchmark once with the active backend.

    The harness does not internally pin the backend per scenario the way
    the parser/query/agent-scan harnesses do, so Phase 7B drives it
    twice: once with ``SASE_CORE_BACKEND=python`` and once with default
    Rust. The caller is responsible for setting / clearing the env var.
    """
    from tests.perf.bench_git_query_ops import run_bench

    raw = run_bench(
        runs=runs,
        warmup=warmup,
        small=small,
        medium=medium,
        large=large,
        e2e_runs=e2e_runs,
        output=None,
        skip_e2e=skip_e2e,
    )
    surface_to_workloads: dict[str, list[dict[str, Any]]] = {
        "parse_git_name_status_z": [],
        "parse_git_branch_name": [],
        "derive_git_workspace_name": [],
        "parse_git_conflicted_files": [],
        "parse_git_local_changes": [],
    }
    for w in raw["workloads"]:
        scenarios = w.get("scenarios", {}) if not w.get("skipped") else {}
        if "parse_git_name_status_z" in scenarios:
            # synthetic_* and end_to_end_* both emit this scenario.
            surface_to_workloads["parse_git_name_status_z"].append(
                {
                    "label": w["label"],
                    "size": {
                        "size_bytes": w.get("size_bytes"),
                        "stream_size_bytes": w.get("stream_size_bytes"),
                        "n_files_seeded": w.get("n_files_seeded"),
                    },
                    # Captures the shipped surface plus the related
                    # subprocess-only/-+parse rows for context.
                    "scenarios": dict(scenarios),
                    "backend_label": backend_label,
                }
            )
        if w.get("label") == "normalizers":
            for scen_name, surface in _GIT_NORMALIZER_SCENARIO_TO_SURFACE.items():
                summary = scenarios.get(scen_name, {})
                surface_to_workloads[surface].append(
                    {
                        "label": "normalizers",
                        "size": {"scenario_name": scen_name},
                        "summary": summary,
                        "backend_label": backend_label,
                    }
                )
    return {
        surface: {
            "tool": "bench_git_query_ops",
            "extra": {
                "small": small,
                "medium": medium,
                "large": large,
                "skip_e2e": skip_e2e,
                "backend_label": backend_label,
            },
            "workloads": workloads,
        }
        for surface, workloads in surface_to_workloads.items()
    }


# ---- summary writer --------------------------------------------------------


def _write_summary_artifact(
    *,
    surface: str,
    tool: str,
    workloads: Sequence[Mapping[str, Any]],
    runs: int,
    warmup: int,
    extra: Mapping[str, Any],
    artifact_dir: Path,
) -> Path:
    """Write a ``rust_backend_phase7_<surface>_summary.json`` artifact."""
    workload_label = workloads[0]["label"] if workloads else f"{surface}_no_workloads"
    metadata = build_metadata(
        tool=tool,
        surface=surface,
        workload=workload_label,
        # ``BackendChoice("summary")`` instead of ``BackendChoice.SUMMARY``
        # so static checkers infer ``BackendChoice`` rather than the
        # ``Literal["summary"]`` value type.
        backend=BackendChoice("summary"),
        runs=runs,
        warmup=warmup,
        extra=extra,
    )

    rendered_workloads: list[dict[str, Any]] = []
    for w in workloads:
        rendered: dict[str, Any] = {
            "label": w["label"],
            "size": w.get("size", {}),
        }
        if "baseline" in w and "candidate" in w:
            comparisons = summarize_report(
                surface=surface,
                workload=w["label"],
                baseline_scenarios=w["baseline"],
                candidate_scenarios=w["candidate"],
                baseline_label="explicit_python",
                candidate_label="default_rust",
            )
            rendered["baseline"] = w["baseline"]
            rendered["candidate"] = w["candidate"]
            rendered["comparisons"] = [c.as_dict() for c in comparisons]
            for raw_key in ("raw_python_scenarios", "raw_rust_scenarios"):
                if raw_key in w:
                    rendered[raw_key] = w[raw_key]
        elif "summary" in w:
            # Single-summary workload (one row, one backend per call).
            rendered["summary"] = w["summary"]
            rendered["backend_label"] = w.get("backend_label")
        elif "scenarios" in w:
            rendered["scenarios"] = w["scenarios"]
            rendered["backend_label"] = w.get("backend_label")
        rendered_workloads.append(rendered)

    report = {
        "metadata": metadata.as_dict(),
        "workloads": rendered_workloads,
    }
    out = artifact_path(
        surface=surface,
        backend_or_summary=BackendChoice.SUMMARY,
        artifact_dir=artifact_dir,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n")
    return out


def _merge_git_workloads(
    *,
    python_run: Mapping[str, Mapping[str, Any]],
    rust_run: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Pair python-backend / rust-backend git query ops runs by workload label.

    The Git query ops harness does not flip the backend per scenario, so
    we run it twice and pair the workloads here. Returns
    ``surface -> {tool, extra, workloads}`` with each workload carrying a
    ``baseline`` and ``candidate`` map that ``_write_summary_artifact``
    can feed straight into ``summarize_report``.
    """
    merged: dict[str, dict[str, Any]] = {}
    for surface, py_payload in python_run.items():
        rust_payload = rust_run.get(surface, {"workloads": []})
        py_workloads = {w["label"]: w for w in py_payload["workloads"]}
        rust_workloads = {w["label"]: w for w in rust_payload["workloads"]}

        labels = list(py_workloads.keys())
        for label in rust_workloads:
            if label not in labels:
                labels.append(label)

        merged_workloads: list[dict[str, Any]] = []
        for label in labels:
            py_w = py_workloads.get(label, {})
            rust_w = rust_workloads.get(label, {})
            if "summary" in py_w or "summary" in rust_w:
                # Normalizer workloads — single scenario per backend.
                merged_workloads.append(
                    {
                        "label": label,
                        "size": (py_w.get("size") or rust_w.get("size") or {}),
                        "baseline": {surface: py_w.get("summary", {})},
                        "candidate": {surface: rust_w.get("summary", {})},
                    }
                )
            else:
                merged_workloads.append(
                    {
                        "label": label,
                        "size": (py_w.get("size") or rust_w.get("size") or {}),
                        "baseline": {
                            surface: (py_w.get("scenarios") or {}).get(surface, {}),
                        },
                        "candidate": {
                            surface: (rust_w.get("scenarios") or {}).get(surface, {}),
                        },
                    }
                )
        merged[surface] = {
            "tool": py_payload.get("tool") or rust_payload.get("tool"),
            "extra": {
                "python_run_extra": py_payload.get("extra", {}),
                "rust_run_extra": rust_payload.get("extra", {}),
            },
            "workloads": merged_workloads,
        }
    return merged


# ---- driver ----------------------------------------------------------------


def _set_backend(value: str | None) -> str | None:
    """Set ``SASE_CORE_BACKEND`` and return the prior value (None if unset)."""
    prior = os.environ.get("SASE_CORE_BACKEND")
    if value is None:
        os.environ.pop("SASE_CORE_BACKEND", None)
    else:
        os.environ["SASE_CORE_BACKEND"] = value
    return prior


def _restore_backend(prior: str | None) -> None:
    if prior is None:
        os.environ.pop("SASE_CORE_BACKEND", None)
    else:
        os.environ["SASE_CORE_BACKEND"] = prior


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

    # All harnesses except `bench_git_query_ops` flip backends per scenario
    # internally, so a single in-process call is enough. The Git query ops
    # harness times only the active backend, so we drive it twice.
    by_surface: dict[str, dict[str, Any]] = {}

    print("\n==== Phase 7B: parser core (bench_core_parse) ====")
    by_surface.update(_bench_core_parse(**cfg["core_parse"]))

    print("\n==== Phase 7B: query core (bench_core_query) ====")
    by_surface.update(_bench_core_query(**cfg["core_query"]))

    print("\n==== Phase 7B: agent scan (bench_agent_scan) ====")
    by_surface.update(_bench_agent_scan(**cfg["agent_scan"], include_home=include_home))

    print("\n==== Phase 7B: status state machine (bench_status_state_machine) ====")
    by_surface.update(_bench_status_state_machine(**cfg["status_state_machine"]))

    print("\n==== Phase 7B: git query ops (bench_git_query_ops, python pass) ====")
    prior = _set_backend("python")
    try:
        py_run = _bench_git_query_ops(**cfg["git_query_ops"], backend_label="python")
    finally:
        _restore_backend(prior)
    print("\n==== Phase 7B: git query ops (bench_git_query_ops, rust default) ====")
    prior = _set_backend(None)  # default = rust
    try:
        rust_run = _bench_git_query_ops(
            **cfg["git_query_ops"], backend_label="default_rust"
        )
    finally:
        _restore_backend(prior)
    by_surface.update(_merge_git_workloads(python_run=py_run, rust_run=rust_run))

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
