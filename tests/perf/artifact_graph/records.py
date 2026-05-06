"""Measurement record helpers for the artifact graph benchmark."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sase.core.artifact_wire import ArtifactMutationResultWire


def mutation_record(
    operation: str,
    latency_ms: float,
    result: ArtifactMutationResultWire,
    *,
    fixture: dict[str, int],
    bounded: bool,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "latency_ms": latency_ms,
        "fixture": fixture,
        "bounded": bounded,
        "mutation_counts": {
            "calls": 1,
            "nodes_added": result.nodes_added,
            "nodes_updated": result.nodes_updated,
            "nodes_removed": result.nodes_removed,
            "links_added": result.links_added,
            "links_updated": result.links_updated,
            "links_removed": result.links_removed,
            "tombstones_added": result.tombstones_added,
        },
        "affected_nodes": len(result.affected_node_ids),
        "affected_links": len(result.affected_link_ids),
        "errors": result.errors,
    }


def query_record(
    operation: str,
    latency_ms: float,
    *,
    fixture: dict[str, int],
    bounded: bool,
    query_count: int,
    result_count: int,
    errors: list[str] | None = None,
    query_counts: dict[str, int] | None = None,
    mutation_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    counted_queries = {"calls": query_count}
    if query_counts:
        counted_queries.update(query_counts)
    record = {
        "operation": operation,
        "latency_ms": latency_ms,
        "fixture": fixture,
        "bounded": bounded,
        "query_counts": counted_queries,
        "result_count": result_count,
        "errors": errors or [],
    }
    if mutation_counts is not None:
        record["mutation_counts"] = mutation_counts
    return record


def time_mutation(
    operation: str,
    fn: Callable[[], ArtifactMutationResultWire],
    *,
    fixture: dict[str, int],
    bounded: bool,
) -> dict[str, Any]:
    start = time.perf_counter()
    result = fn()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return mutation_record(
        operation, elapsed_ms, result, fixture=fixture, bounded=bounded
    )
