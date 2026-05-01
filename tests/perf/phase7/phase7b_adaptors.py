"""Per-harness adaptors for Phase 7B (sase-1e.2).

Each adaptor runs an existing core-operation benchmark in-process and
returns a dict mapping ``surface -> {tool, extra, workloads}`` shaped
so :mod:`tests.perf.phase7.phase7b_summary` can feed it straight into
``summarize_report``.

Workload shape::

    {
        "label": str,
        "size": dict,     # any size hints (size_bytes, num_specs, etc.)
        "baseline": dict[scenario_name -> summary],
        "candidate": dict[scenario_name -> summary],
    }

Reused from :mod:`tests.perf.phase7_check_regression` to drive Phase 7E
floor checks against the same harness orchestration as Phase 7B.
"""

from __future__ import annotations

from typing import Any


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
        if w.get("skipped"):
            continue
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
        # against; skip parse-only and explicitly skipped local-only workloads.
        if w.get("num_specs") and scenarios:
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
                        "legacy_direct": scenarios.get(
                            "rust_legacy_direct_evaluate_many", {}
                        ),
                        "persistent_corpus_compile": scenarios.get(
                            "rust_persistent_corpus_compile", {}
                        ),
                        "persistent_fully_compiled": scenarios.get(
                            "rust_persistent_fully_compiled_evaluate_many", {}
                        ),
                        "persistent_query_keystroke": scenarios.get(
                            "rust_persistent_query_keystroke_evaluate_many", {}
                        ),
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
            "extra": {
                "spec_sizes": list(spec_sizes),
                "persistent_corpus_anchor_policy": (
                    "Anchor persistent_query_keystroke only after the "
                    "query_corpus_phase4_routing_gate passes on "
                    "synthetic_100, synthetic_1000, and synthetic_10000."
                ),
                "raw_gate": raw.get("gate", {}),
            },
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
        scenarios = w.get("scenarios", {})
        # Pure-helper workloads carry the shipped scenarios; transition
        # workloads do not, so skip them — they belong to the higher-level
        # orchestrator, not to the shipped Rust core ops covered here.
        if "read_status_from_lines" not in scenarios:
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
                    "candidate": {surface: scenarios.get(surface, {})},
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
    twice (historical Phase 7B compared two backends; post-Phase-8 the
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
