"""Shared batched artifact-summary loading for CL and Agent rows."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sase.core import artifact_facade
from sase.core.artifact_wire import ArtifactSummaryRequestWire, ArtifactSummaryWire

from ..artifact_graph_refresh import default_artifact_index_path
from ..models.artifact_summary_cache import ArtifactSummaryCache

if TYPE_CHECKING:
    from ...changespec import ChangeSpec
    from ..models import Agent


def _load_missing_artifact_summaries(
    cache: ArtifactSummaryCache,
    artifact_ids: Iterable[str | None],
) -> list[ArtifactSummaryWire]:
    """Load uncached artifact summaries in one quiet batched facade call."""

    missing = tuple(_iter_missing_ids(cache, artifact_ids))
    if not missing:
        return []

    try:
        summaries = artifact_facade.artifact_summary(
            default_artifact_index_path(),
            ArtifactSummaryRequestWire(artifact_ids=missing),
        )
    except Exception as exc:
        cache.mark_error(missing, str(exc))
        return []

    cache.update(summaries)
    returned_ids = {summary.artifact_id for summary in summaries}
    unreturned = tuple(
        artifact_id for artifact_id in missing if artifact_id not in returned_ids
    )
    if unreturned:
        cache.mark_missing(unreturned)
    return summaries


def load_changespec_artifact_summaries(
    cache: ArtifactSummaryCache,
    changespecs: Iterable[ChangeSpec],
) -> list[ArtifactSummaryWire]:
    return _load_missing_artifact_summaries(
        cache,
        (changespec.name for changespec in changespecs),
    )


def load_agent_artifact_summaries(
    cache: ArtifactSummaryCache,
    agents: Iterable[Agent],
) -> list[ArtifactSummaryWire]:
    from .artifacts import agent_artifact_id

    return _load_missing_artifact_summaries(
        cache,
        (agent_artifact_id(agent) for agent in agents),
    )


def _iter_missing_ids(
    cache: ArtifactSummaryCache,
    artifact_ids: Iterable[str | None],
) -> Iterable[str]:
    seen: set[str] = set()
    for artifact_id in artifact_ids:
        if not artifact_id or artifact_id in seen or cache.has(artifact_id):
            continue
        seen.add(artifact_id)
        yield artifact_id


__all__ = [
    "load_agent_artifact_summaries",
    "load_changespec_artifact_summaries",
]
