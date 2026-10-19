"""Versioned JSON envelope shared by every ``sase stats`` view."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Mapping
from typing import Any

import sase
from sase.stats.project.view import ProjectStatsView

PROJECT_STATS_SCHEMA = "sase.stats.project"
STATS_ENVELOPE_SCHEMA_VERSION = 1


def _build_stats_envelope(
    *,
    schema: str,
    generated_at: str,
    machine: str,
    query: Mapping[str, Any],
    versions: Mapping[str, Any],
    data: Mapping[str, Any],
    schema_version: int = STATS_ENVELOPE_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Build one additive-only stats envelope. ``data`` is stored verbatim."""
    return {
        "schema": schema,
        "schema_version": schema_version,
        "generated_at": generated_at,
        "machine": machine,
        "query": dict(query),
        "versions": dict(versions),
        "data": data,
    }


def project_stats_envelope(view: ProjectStatsView) -> dict[str, Any]:
    """Wrap a Projects report in the shared stats envelope."""
    query = view.query
    return _build_stats_envelope(
        schema=PROJECT_STATS_SCHEMA,
        generated_at=view.generated_at,
        machine=view.machine,
        query={
            "projects": [project.key for project in view.projects],
            "range": {
                "preset": query.preset,
                "start_ts": query.range.start_ts,
                "end_ts": query.range.end_ts,
                "label": query.range.display_label,
            },
            "timezone": view.timezone,
            "group_by": view.effective_group_by,
        },
        versions=stats_runtime_versions(view),
        data=view.data,
    )


def stats_runtime_versions(
    view: ProjectStatsView | None = None,
) -> dict[str, Any]:
    """Host, core, and metric-policy versions stamped on every envelope."""
    metric_policy = 1
    if view is not None:
        metric_policy = int(view.data.get("metric_policy_version") or 1)
    return {
        "sase": str(sase.__version__),
        "sase_core": _sase_core_version(),
        "metric_policy": metric_policy,
    }


def _sase_core_version() -> str:
    try:
        return importlib.metadata.version("sase-core-rs")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


__all__ = [
    "PROJECT_STATS_SCHEMA",
    "STATS_ENVELOPE_SCHEMA_VERSION",
    "project_stats_envelope",
    "stats_runtime_versions",
]
