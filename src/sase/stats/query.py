"""Thin adapters for the Rust agent-statistics bindings."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from sase.core.agent_scan_facade import default_agent_artifact_index_path
from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.stats.ranges import bucket_seconds_for

RuntimeGroupBy = Literal[
    "tribe",
    "clan",
    "session",
    # legacy agent-family spelling: see ``LEGACY_RUNTIME_GROUP_BY``.
    "family",
    "agent",
    "provider",
    "model",
    "workflow",
    "project",
    "patch",
]
# legacy agent-family spelling: stored or configured group-bys carry
# ``"family"``; new writers emit only ``"session"``. Core accepts the alias
# and returns ``"session"``.
LEGACY_RUNTIME_GROUP_BY = "family"


def _normalize_runtime_group_by(value: str) -> str:
    """Map a stored or requested group-by to the spelling sent to core."""
    return "session" if value == LEGACY_RUNTIME_GROUP_BY else value


def query_run_stats(
    *,
    start_ts: int,
    end_ts: int,
    runtime_group_by: RuntimeGroupBy = "agent",
    bucket_seconds: int | None = None,
    top_n: int = 5,
    project: str | None = None,
    work_top_n: int = 50,
    xprompt_top_n: int = 40,
    xprompt_breakdown_top_n: int = 5,
    xprompt_focus: str | None = None,
    index_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return the composite run-backed statistics payload for one window."""
    resolved_index = (
        Path(index_path).expanduser()
        if index_path is not None
        else default_agent_artifact_index_path()
    )
    resolved_bucket_seconds = (
        bucket_seconds
        if bucket_seconds is not None
        else bucket_seconds_for(start_ts, end_ts)
    )
    binding = require_rust_binding("agent_stats_query_runs")
    payload: dict[str, Any] = binding(
        str(resolved_index),
        {
            "start_ts": int(start_ts),
            "end_ts": int(end_ts),
            "runtime_group_by": _normalize_runtime_group_by(runtime_group_by),
            "bucket_seconds": int(resolved_bucket_seconds),
            "top_n": int(top_n),
            "project": project,
            "work_top_n": int(work_top_n),
            "xprompt_top_n": int(xprompt_top_n),
            "xprompt_breakdown_top_n": int(xprompt_breakdown_top_n),
            "xprompt_focus": xprompt_focus,
        },
    )
    return payload


def query_activity_stats(
    *,
    start_ts: int,
    end_ts: int,
    top_n: int = 5,
    project: str | None = None,
    index_path: Path | str | None = None,
    home_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return durable skill, memory, plan, and question statistics."""
    resolved_home = (
        Path(home_path).expanduser() if home_path is not None else sase_home()
    )
    resolved_index = (
        Path(index_path).expanduser()
        if index_path is not None
        else default_agent_artifact_index_path(resolved_home)
    )
    binding = require_rust_binding("agent_stats_query_activity")
    payload: dict[str, Any] = binding(
        str(resolved_index),
        str(resolved_home),
        {
            "start_ts": int(start_ts),
            "end_ts": int(end_ts),
            "top_n": int(top_n),
            "project": project,
        },
    )
    return payload


__all__ = [
    "LEGACY_RUNTIME_GROUP_BY",
    "RuntimeGroupBy",
    "query_activity_stats",
    "query_run_stats",
]
