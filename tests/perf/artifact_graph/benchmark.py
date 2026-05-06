"""Artifact graph benchmark orchestration."""

from __future__ import annotations

import asyncio
from typing import Any

from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
)

from .common import ensure_extension, summarize
from .fixture_measurements import run_fixture_measurements
from .modal_measurements import run_modal_measurements
from .startup_measurements import measure_startup_contract_sentinel


def _summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["operation"]), []).append(record)
    return {
        operation: {
            "latency": summarize([float(item["latency_ms"]) for item in items]),
            "bounded": items[0]["bounded"],
            "fixture": items[0]["fixture"],
            "result_count": summarize(
                [
                    float(item["result_count"])
                    for item in items
                    if "result_count" in item
                ]
            ),
            "query_calls": summarize(
                [
                    float(item["query_counts"]["calls"])
                    for item in items
                    if "query_counts" in item
                ]
            ),
            "mutation_calls": summarize(
                [
                    float(item["mutation_counts"]["calls"])
                    for item in items
                    if "mutation_counts" in item and "calls" in item["mutation_counts"]
                ]
            ),
            "errors": [error for item in items for error in item.get("errors", [])],
        }
        for operation, items in grouped.items()
    }


def run_benchmark(
    *,
    runs: int,
    project_count: int,
    bead_count: int,
    agent_count: int,
    modal_linked_count: int,
) -> dict[str, Any]:
    ensure_extension()
    records: list[dict[str, Any]] = []
    for _ in range(runs):
        records.append(measure_startup_contract_sentinel())
        records.append(
            measure_startup_contract_sentinel(
                operation="startup_contract:missing_index_no_broad_artifact_graph_calls",
                fixture={"index_exists": 0},
            )
        )
        records.extend(
            run_fixture_measurements(
                project_count=project_count,
                bead_count=bead_count,
                agent_count=agent_count,
            )
        )
        records.extend(
            asyncio.run(run_modal_measurements(linked_count=modal_linked_count))
        )
    return {
        "schema_version": ARTIFACT_WIRE_SCHEMA_VERSION,
        "runs": runs,
        "operations": _summarize_records(records),
        "measurements": records,
    }
