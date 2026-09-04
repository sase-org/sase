"""Orchestrates the registry-spined, index-enriched catalog snapshot build."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.agent.names import load_name_registry

from ._derive import (
    classify_kind,
    derive_patch,
    has_attention,
    is_dismissed,
    is_retrying,
    is_durably_revivable,
    known_project_keys,
)
from ._family import family_and_role
from ._models import AgentCatalogBuildError, AgentCatalogRow, AgentCatalogSnapshot
from ._sources import (
    ArtifactIndexRecord,
    DismissedBundleSummary,
    load_artifact_index_projection,
    load_dismissed_child_fallback,
    load_dismissed_top_level,
)

_FACET_FIELDS = (
    "status",
    "role",
    "model",
    "llm_provider",
    "project",
    "tribe",
    "workflow",
)


def build_agent_catalog_snapshot(
    *,
    artifact_index_path: Path | str | None = None,
) -> AgentCatalogSnapshot:
    """Build the complete agent catalog snapshot.

    Spined on the agent name registry (the only complete name index) and
    left-joined against the artifact index and the dismissed bundle
    archive; every registry name becomes exactly one row, degraded rather
    than dropped when neither enrichment source has anything for it.
    """
    registry = load_name_registry()
    entries: Mapping[str, Mapping[str, Any]] = registry.get("entries", {})

    artifact_index = load_artifact_index_projection(artifact_index_path)

    top_by_suffix = _index_top_level_dismissed(load_dismissed_top_level())

    leftover_suffixes = frozenset(
        raw_suffix
        for entry in entries.values()
        if (raw_suffix := entry.get("raw_suffix")) and raw_suffix not in top_by_suffix
    )
    child_by_suffix = load_dismissed_child_fallback(leftover_suffixes)

    known_keys = known_project_keys()

    rows: list[AgentCatalogRow] = []
    enriched_count = 0
    for name, entry in entries.items():
        row = _build_row(
            name=name,
            entry=entry,
            artifact_index=artifact_index,
            top_by_suffix=top_by_suffix,
            child_by_suffix=child_by_suffix,
            known_keys=known_keys,
        )
        rows.append(row)
        if row.from_artifact_index or row.from_dismissed_archive:
            enriched_count += 1

    return AgentCatalogSnapshot(
        rows=tuple(rows),
        registry_entry_count=len(entries),
        artifact_index_row_count=len(artifact_index),
        dismissed_summary_count=len(top_by_suffix),
        enriched_count=enriched_count,
        thin_count=len(rows) - enriched_count,
        facets=_compute_facets(rows),
    )


def _index_top_level_dismissed(
    summaries: Sequence[DismissedBundleSummary],
) -> dict[str, DismissedBundleSummary]:
    by_suffix: dict[str, DismissedBundleSummary] = {}
    collisions = 0
    for summary in summaries:
        if summary.raw_suffix in by_suffix:
            collisions += 1
            continue
        by_suffix[summary.raw_suffix] = summary
    if collisions:
        raise AgentCatalogBuildError(
            f"{collisions} raw_suffix collision(s) in the top-level dismissed "
            "archive join; the join must be 0-ambiguous "
            "(load_dismissed_bundle_summaries(top_level_only=True) is "
            "documented as unique per raw_suffix)"
        )
    return by_suffix


def _build_row(
    *,
    name: str,
    entry: Mapping[str, Any],
    artifact_index: Mapping[str, ArtifactIndexRecord],
    top_by_suffix: Mapping[str, DismissedBundleSummary],
    child_by_suffix: Mapping[str, DismissedBundleSummary],
    known_keys: frozenset[str],
) -> AgentCatalogRow:
    artifacts_dir = entry.get("artifacts_dir")
    raw_suffix = entry.get("raw_suffix")

    index_record = artifact_index.get(artifacts_dir) if artifacts_dir else None

    dismissed_record = top_by_suffix.get(raw_suffix) if raw_suffix else None
    is_workflow_child = False
    if dismissed_record is None and raw_suffix:
        dismissed_record = child_by_suffix.get(raw_suffix)
        is_workflow_child = dismissed_record is not None

    family, role = family_and_role(name)

    agent_type = _first(
        index_record.agent_type if index_record else None,
        dismissed_record.agent_type if dismissed_record else None,
    )
    kind = classify_kind(
        name=name,
        container_kind=entry.get("container_kind"),
        reservation_kind=entry.get("reservation_kind"),
        agent_type=agent_type,
        is_workflow_child=is_workflow_child,
    )

    state = entry.get("state")
    dismissed = is_dismissed(state)
    bundle_path = dismissed_record.bundle_path if dismissed_record else None
    durably_revivable = (
        dismissed_record.durably_revivable if dismissed_record else False
    )

    clan = (
        name if "clan" in kind else (index_record.agent_clan if index_record else None)
    )

    retry_attempt = _first(
        index_record.retry_attempt if index_record else None,
        dismissed_record.retry_attempt if dismissed_record else None,
    )
    retry_of_timestamp = _first(
        index_record.retry_of_timestamp if index_record else None,
        dismissed_record.retry_of_timestamp if dismissed_record else None,
    )
    retried_as_timestamp = _first(
        index_record.retried_as_timestamp if index_record else None,
        dismissed_record.retried_as_timestamp if dismissed_record else None,
    )
    retry_chain_root_timestamp = _first(
        index_record.retry_chain_root_timestamp if index_record else None,
        dismissed_record.retry_chain_root_timestamp if dismissed_record else None,
    )

    status = _first(
        index_record.status if index_record else None,
        dismissed_record.status if dismissed_record else None,
    )

    patch = derive_patch(
        cl_name=_first(
            index_record.cl_name if index_record else None,
            dismissed_record.cl_name if dismissed_record else None,
        ),
        meta_patch=dismissed_record.meta_patch if dismissed_record else None,
        known_keys=known_keys,
    )

    return AgentCatalogRow(
        name=name,
        canonical_global_name=entry.get("canonical_global_name"),
        kind=kind,
        project=_first(
            entry.get("project_name"),
            index_record.project_name if index_record else None,
        ),
        state=state,
        family=family,
        role=role,
        clan=clan,
        tribe=index_record.clan_tribe if index_record else None,
        workflow=_first(
            index_record.workflow_name if index_record else None,
            dismissed_record.workflow if dismissed_record else None,
        ),
        parent_timestamp=_first(
            index_record.parent_timestamp if index_record else None,
            dismissed_record.parent_timestamp if dismissed_record else None,
        ),
        raw_suffix=raw_suffix,
        artifacts_dir=artifacts_dir,
        bundle_path=bundle_path,
        model=_first(
            index_record.model if index_record else None,
            dismissed_record.model if dismissed_record else None,
        ),
        llm_provider=_first(
            index_record.llm_provider if index_record else None,
            dismissed_record.llm_provider if dismissed_record else None,
        ),
        status=status,
        hidden=bool(index_record.hidden) if index_record else False,
        started_at=_first(
            index_record.started_at if index_record else None,
            dismissed_record.start_time if dismissed_record else None,
        ),
        finished_at=index_record.finished_at if index_record else None,
        retry_attempt=retry_attempt,
        retry_of_timestamp=retry_of_timestamp,
        retried_as_timestamp=retried_as_timestamp,
        retry_chain_root_timestamp=retry_chain_root_timestamp,
        patch=patch,
        dismissed=dismissed,
        revivable=is_durably_revivable(
            dismissed=dismissed,
            bundle_path=bundle_path,
            durably_revivable=durably_revivable,
        ),
        historically_viewable=(
            dismissed_record.historically_viewable if dismissed_record else False
        ),
        durably_revivable=durably_revivable,
        restartable=dismissed_record.restartable if dismissed_record else False,
        missing_requirements=(
            dismissed_record.missing_requirements if dismissed_record else ()
        ),
        attention=has_attention(status),
        retry=is_retrying(
            retry_attempt=retry_attempt,
            retry_of_timestamp=retry_of_timestamp,
            retried_as_timestamp=retried_as_timestamp,
            retry_chain_root_timestamp=retry_chain_root_timestamp,
        ),
        has_collision_history=bool(entry.get("collision_owners")),
        from_artifact_index=index_record is not None,
        from_dismissed_archive=dismissed_record is not None,
    )


def _first(*values: str | int | float | None) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _compute_facets(rows: Sequence[AgentCatalogRow]) -> Mapping[str, tuple[str, ...]]:
    observed: dict[str, set[str]] = {field: set() for field in _FACET_FIELDS}
    for row in rows:
        for field in _FACET_FIELDS:
            value = getattr(row, field)
            if value:
                observed[field].add(value)
    return {field: tuple(sorted(values)) for field, values in observed.items()}
