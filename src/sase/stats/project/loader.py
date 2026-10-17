"""The single project statistics load path used by CLI and TUI workers."""

from collections.abc import Collection
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from sase.config import get_local_machine_name
from sase.core.agent_artifact_index_lock import agent_artifact_index_operation_lock
from sase.core.project_stats_facade import query_project_stats

from .query import (
    ALL_FACETS,
    ProjectStatsFacet,
    ProjectStatsQuery,
    ProjectStatsUnavailableError,
)
from .request import build_project_stats_request
from .view import ProjectStatsView, build_project_stats_view


def load_project_stats(
    query: ProjectStatsQuery,
    *,
    facets: Collection[ProjectStatsFacet] = ALL_FACETS,
    now: datetime | None = None,
    machine: str | None = None,
) -> ProjectStatsView:
    """Read local sources off-thread and preserve partial measurements."""
    current = now or datetime.now(UTC)
    try:
        request = build_project_stats_request(
            query, facets=facets, now_ts=int(current.timestamp())
        )
        # Core also reads runs to select disabled and unregistered projects.
        needs_runs = (
            "runs" in facets
            or request.data["include_run_only_projects"]
            or any(
                project["selection"] == "if_runs"
                for project in request.data["projects"]
            )
        )
        with agent_artifact_index_operation_lock() if needs_runs else nullcontext():
            data = query_project_stats(request.data)
    except (ImportError, AttributeError, OSError, RuntimeError) as exc:
        raise ProjectStatsUnavailableError(str(exc)) from exc
    if _all_sources_failed(data, facets):
        raise ProjectStatsUnavailableError(
            "No project statistics source could be measured: "
            + "; ".join(issue["message"] for issue in data["issues"])
        )
    return build_project_stats_view(
        data,
        query,
        machine=machine
        if machine is not None
        else (get_local_machine_name() or "unknown"),
        generated_at=current.astimezone(UTC).isoformat(),
        timezone=request.data["timezone"],
        facets=facets,
        display_snapshot=request.refs.display_snapshot,
        issues=request.issues,
    )


def _all_sources_failed(
    data: dict[str, Any], facets: Collection[ProjectStatsFacet]
) -> bool:
    if not data["issues"]:
        return False
    portfolio = data["portfolio"]
    output = portfolio.get("output")
    if "output" in facets and output is not None:
        if (
            output.get("commits") is not None
            or output.get("plans_committed") is not None
        ):
            return False
    code = portfolio.get("code")
    if "code" in facets and code is not None and code.get("repos_measured", 0) > 0:
        return False
    if "runs" in facets and portfolio.get("runs") is not None:
        return False
    # Metadata-only record snapshots are measurements too.
    return not any(
        repo.get("snapshot") is not None
        for project in data["projects"]
        for repo in project["repos"]
    )
