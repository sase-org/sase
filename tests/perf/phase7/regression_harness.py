"""Harness routing and sample configuration for the Phase 7 floor check."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tests.perf.phase7.regression_floor import _AnchorSpec


# Phase 7B already has one adaptor per harness in run_phase7b.py. Grouping
# surfaces here lets the floor check reuse those adaptors without duplicating
# their per-harness orchestration.
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
    # Five is still cheap enough for CI while making the median substantially
    # less sensitive to one contended hosted-runner sample than the old three.
    notification_store={"runs": 5, "warmup": 1, "count": 5_000},
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
    :func:`tests.perf.phase7.run_phase7b` so the lookup logic can treat both
    code paths identically.
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
