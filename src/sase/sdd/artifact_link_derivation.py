"""Host call sites that turn derivation candidates into persisted rows.

Wraps the Textual-free rules in :mod:`sase.artifact_links.derive` with the
store and commit plumbing every call site needs: build validated rows from
candidates, upsert them, and commit through the normal artifact-link store
path in one batch. Every call site is best-effort -- a persistence failure is
reported in the outcome rather than raised, since no caller here (a plan
handoff, an artifact creation, a background sweep) may be broken by a
derivation error.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sase.artifact_links.derive import (
    DerivableDocument,
    artifact_link_derivation_enabled,
    derive_candidate_links,
)
from sase.sdd._artifact_link_commit import (
    ArtifactLinkPersistError,
    persist_artifact_link_graph_mutation,
)
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
)


@dataclass(frozen=True)
class ArtifactLinkDerivationOutcome:
    """Result of one derive-and-persist pass over a set of documents."""

    candidates: int = 0
    persisted: int = 0
    errors: tuple[str, ...] = ()


def derive_and_persist_artifact_links(
    store: ArtifactLinkStore,
    documents: Sequence[DerivableDocument],
    *,
    created_by: str,
    artifacts_dir: str | Path | None = None,
) -> ArtifactLinkDerivationOutcome:
    """Derive candidate rows for *documents* and persist them via *store*.

    A no-op, including the known-bead-ids read the ``implements`` rule needs,
    when the beta flag is off or *documents* is empty. Every persisted row is
    committed together in at most one scoped commit rather than one per row.
    """

    if not documents or not artifact_link_derivation_enabled():
        return ArtifactLinkDerivationOutcome()

    candidates = derive_candidate_links(
        documents, known_bead_ids=_known_bead_ids(store)
    )
    if not candidates:
        return ArtifactLinkDerivationOutcome()

    now = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    changed_indexes: list[Path] = []
    beads_changed = False
    persisted = 0
    errors: list[str] = []
    for candidate in candidates:
        row = {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "source_ref": candidate.source_ref,
            "relation": candidate.relation,
            "target_ref": candidate.target_ref,
            "description": candidate.description,
            "origin": candidate.origin,
            "created_by": created_by,
            "created_at": now,
            "uses": 1,
        }
        try:
            outcome = store.upsert_row(row)
        except (RuntimeError, TypeError, ValueError) as exc:
            errors.append(
                f"{candidate.source_ref} {candidate.relation} "
                f"{candidate.target_ref}: {exc}"
            )
            continue
        changed_indexes.extend(
            Path(path) for path in outcome.get("changed_indexes") or ()
        )
        beads_changed = beads_changed or bool(outcome.get("beads_changed"))
        persisted += 1

    if changed_indexes or beads_changed:
        try:
            persist_artifact_link_graph_mutation(
                store,
                changed_indexes=tuple(dict.fromkeys(changed_indexes)),
                beads_changed=beads_changed,
                artifacts_dir=artifacts_dir,
            )
        except ArtifactLinkPersistError as exc:
            errors.append(str(exc))

    return ArtifactLinkDerivationOutcome(
        candidates=len(candidates), persisted=persisted, errors=tuple(errors)
    )


def _known_bead_ids(store: ArtifactLinkStore) -> frozenset[str]:
    if store.sdd_store is None:
        return frozenset()
    from sase.bead_pages.links import known_bead_ids_for_store

    return known_bead_ids_for_store(store.sdd_store) or frozenset()


__all__ = [
    "ArtifactLinkDerivationOutcome",
    "derive_and_persist_artifact_links",
]
