"""Informational coverage counters for derived artifact links."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.artifact_cli._link_health_constants import RESOLVED_STATUSES
from sase.artifact_cli._link_health_refs import known_bead_ids
from sase.artifact_cli.references import resolve_cli_reference
from sase.artifact_links.derive import derive_candidate_links
from sase.artifact_refs import ArtifactRefContext
from sase.sdd._artifact_link_store_support import kind_of_ref
from sase.sdd.artifact_link_store import ArtifactLinkStore


@dataclass(frozen=True)
class _ArtifactLinkCoveragePopulation:
    """Coverage for one derivable hard-evidence population."""

    name: str
    linked: int
    total: int


@dataclass(frozen=True)
class ArtifactLinkCoverageReport:
    """Informational coverage counters for derived artifact links."""

    populations: tuple[_ArtifactLinkCoveragePopulation, ...] = ()
    rows_by_origin: tuple[tuple[str, int], ...] = ()
    rows_by_relation: tuple[tuple[str, int], ...] = ()


def read_row_count(rows: tuple[dict[str, Any], ...]) -> int:
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        if str(row.get("relation") or "") != "read":
            continue
        seen.add(
            (
                str(row.get("source_ref") or ""),
                "read",
                str(row.get("target_ref") or ""),
            )
        )
    return len(seen)


def coverage_report(
    store: ArtifactLinkStore,
    rows: list[dict[str, Any]],
    *,
    context: ArtifactRefContext,
    index_rows: list[dict[str, Any]] | None = None,
) -> ArtifactLinkCoverageReport:
    # `rows` (the caller's store-backed view) excludes projected rows, but the
    # origin/relation breakdown is diagnostic, not a durable-truth read, so it
    # counts every row in the aggregate -- including projected ones.
    all_rows = (
        index_rows if index_rows is not None else store.load_aggregate().get("rows", [])
    )
    origin_counts = Counter(str(row.get("origin") or "unknown") for row in all_rows)
    relation_counts = Counter(str(row.get("relation") or "unknown") for row in all_rows)
    existing = _exact_row_keys(rows)
    populations: dict[str, set[tuple[str, str, str]]] = {}
    try:
        from sase.sdd.artifact_link_backfill import sweepable_artifact_link_documents

        candidates = derive_candidate_links(
            sweepable_artifact_link_documents(store),
            known_bead_ids=frozenset(known_bead_ids(store) or ()),
            agents_sidecar_root=_agents_sidecar_root(store),
            is_agent_published=lambda name: _is_agent_published(name, context=context),
        )
    except Exception:  # noqa: BLE001 - coverage is a report, not a gate.
        candidates = ()

    for candidate in candidates:
        population = _coverage_population(
            candidate.source_ref,
            candidate.relation,
            candidate.target_ref,
        )
        if population is None:
            continue
        populations.setdefault(population, set()).add(
            (candidate.source_ref, candidate.relation, candidate.target_ref)
        )

    coverage = tuple(
        _ArtifactLinkCoveragePopulation(
            name=name,
            linked=sum(1 for key in keys if key in existing),
            total=len(keys),
        )
        for name, keys in sorted(populations.items())
    )
    return ArtifactLinkCoverageReport(
        populations=coverage,
        rows_by_origin=tuple(sorted(origin_counts.items())),
        rows_by_relation=tuple(sorted(relation_counts.items())),
    )


def _exact_row_keys(
    rows: list[dict[str, Any]],
) -> frozenset[tuple[str, str, str]]:
    return frozenset(
        (
            str(row.get("source_ref") or ""),
            str(row.get("relation") or ""),
            str(row.get("target_ref") or ""),
        )
        for row in rows
        if row.get("source_ref") and row.get("relation") and row.get("target_ref")
    )


def _coverage_population(
    source_ref: str,
    relation: str,
    target_ref: str,
) -> str | None:
    source_kind = kind_of_ref(source_ref)
    target_kind = kind_of_ref(target_ref)
    if source_kind == "plan" and relation == "implements" and target_kind == "bead":
        return "plan bead_id implements"
    if (
        source_kind == "research"
        and relation == "derives-from"
        and target_kind == "research"
    ):
        return "research-swarm filename lineage"
    if source_kind == "agent" and relation == "cites" and target_kind == "plan":
        return "prompt header cites"
    return None


def _agents_sidecar_root(store: ArtifactLinkStore) -> Path | None:
    if store.sdd_store is None:
        return None
    from sase.sdd.store import AGENTS_SIDECAR_ROLE

    try:
        root = store.sdd_store.kind_root(AGENTS_SIDECAR_ROLE)
    except Exception:  # noqa: BLE001 - no agents sidecar, no coverage candidates.
        return None
    return root if root.is_dir() else None


def _is_agent_published(agent_name: str, *, context: ArtifactRefContext) -> bool:
    try:
        result = resolve_cli_reference(f"agent:{agent_name}", context=context)
    except Exception:  # noqa: BLE001 - unpublished agents are not covered rows.
        return False
    return result.resolution.status in RESOLVED_STATUSES


__all__ = [
    "ArtifactLinkCoverageReport",
    "coverage_report",
    "read_row_count",
]
