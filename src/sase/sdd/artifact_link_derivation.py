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

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sase.artifact_links.derive import (
    DerivableDocument,
    DerivedLinkCandidate,
    derive_candidate_links,
)
from sase.artifact_ref_models import ArtifactRefContext
from sase.sdd._artifact_link_store_support import validate_artifact_link_row
from sase.sdd._artifact_link_commit import (
    ArtifactLinkPersistError,
    persist_artifact_link_graph_mutation,
)
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
)


@dataclass(frozen=True)
class _ArtifactLinkDerivationOutcome:
    """Result of one derive-and-persist pass over a set of documents."""

    candidates: int = 0
    persisted: int = 0
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactLinkDerivationInputs:
    """Store-scoped facts reused across related derivation passes."""

    known_bead_ids: Collection[str]
    agents_sidecar_root: Path | None
    is_agent_published: Callable[[str], bool]


def artifact_link_derivation_inputs(
    store: ArtifactLinkStore,
) -> ArtifactLinkDerivationInputs:
    """Load reusable store-scoped derivation inputs once."""

    context = _artifact_ref_context_for_store(store)
    return ArtifactLinkDerivationInputs(
        known_bead_ids=_known_bead_ids(store),
        agents_sidecar_root=_agents_sidecar_root(store),
        is_agent_published=lambda name: _is_agent_published(name, context=context),
    )


def derive_and_persist_artifact_links(
    store: ArtifactLinkStore,
    documents: Sequence[DerivableDocument],
    *,
    created_by: str,
    artifacts_dir: str | Path | None = None,
    derivation_inputs: ArtifactLinkDerivationInputs | None = None,
) -> _ArtifactLinkDerivationOutcome:
    """Derive candidate rows for *documents* and persist them via *store*.

    A no-op, including the known-bead-ids read the ``implements`` rule needs,
    when *documents* is empty. Every persisted row is committed together in at
    most one scoped commit rather than one per row.
    """

    if not documents:
        return _ArtifactLinkDerivationOutcome()

    inputs = derivation_inputs or artifact_link_derivation_inputs(store)
    candidates = derive_candidate_links(
        documents,
        known_bead_ids=inputs.known_bead_ids,
        agents_sidecar_root=inputs.agents_sidecar_root,
        is_agent_published=inputs.is_agent_published,
    )
    return persist_derived_link_candidates(
        store,
        candidates,
        created_by=created_by,
        artifacts_dir=artifacts_dir,
    )


def persist_derived_link_candidates(
    store: ArtifactLinkStore,
    candidates: Sequence[DerivedLinkCandidate],
    *,
    created_by: str,
    artifacts_dir: str | Path | None = None,
) -> _ArtifactLinkDerivationOutcome:
    """Persist already-derived candidate rows via *store*."""

    if not candidates:
        return _ArtifactLinkDerivationOutcome()

    now = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    changed_indexes: list[Path] = []
    beads_changed = False
    persisted = 0
    errors: list[str] = []
    for candidate in candidates:
        incoming = {
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
            row = validate_artifact_link_row(incoming)
            outcome: dict[str, object] | None = None
            for ref in (str(row["source_ref"]), str(row["target_ref"])):
                written = store._upsert_sidecar(ref, row)
                if written is not None:
                    outcome = written
                    changed_indexes.extend(
                        Path(path) for path in written.get("changed_indexes") or ()
                    )
            bead_written = store._upsert_bead(row)
            if bead_written is not None:
                outcome = bead_written
                beads_changed = (
                    beads_changed or str(bead_written.get("kind") or "") != "unchanged"
                )
            elif store._is_aggregate_only(row):
                outcome = store._upsert_aggregate_row(row)
        except (RuntimeError, TypeError, ValueError) as exc:
            errors.append(
                f"{candidate.source_ref} {candidate.relation} "
                f"{candidate.target_ref}: {exc}"
            )
            continue
        outcome = outcome or {"kind": "unchanged"}
        persisted += 1

    store.rebuild_aggregate()
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

    return _ArtifactLinkDerivationOutcome(
        candidates=len(candidates), persisted=persisted, errors=tuple(errors)
    )


def _known_bead_ids(store: ArtifactLinkStore) -> frozenset[str]:
    if store.sdd_store is None:
        return frozenset()
    from sase.bead_pages.links import known_bead_ids_for_store

    return known_bead_ids_for_store(store.sdd_store) or frozenset()


_PUBLISHED_AGENT_STATUSES = frozenset({"exact", "drifted", "vcs_backed"})


def _agents_sidecar_root(store: ArtifactLinkStore) -> Path | None:
    if store.sdd_store is None:
        return None
    from sase.sdd.store import AGENTS_SIDECAR_ROLE

    try:
        root = store.sdd_store.kind_root(AGENTS_SIDECAR_ROLE)
    except Exception:  # noqa: BLE001 - no agents sidecar, no candidates.
        return None
    return root if root.is_dir() else None


def _is_agent_published(
    agent_name: str, *, context: ArtifactRefContext | None = None
) -> bool:
    try:
        from sase.artifact_cli.references import resolve_cli_reference

        result = resolve_cli_reference(f"agent:{agent_name}", context=context)
    except Exception:  # noqa: BLE001 - unresolved agents contribute no candidate.
        return False
    return result.resolution.status in _PUBLISHED_AGENT_STATUSES


def _artifact_ref_context_for_store(
    store: ArtifactLinkStore,
) -> ArtifactRefContext | None:
    if store.sdd_store is None:
        return None
    try:
        from sase.artifact_ref_context import artifact_ref_context
        from sase.workspace_provider import find_marker_from_cwd
    except Exception:  # noqa: BLE001 - fall back to cwd-based resolution.
        return None
    roots = (store.sdd_store.repo_root, *store.sidecar_roots.values())
    for root in roots:
        try:
            found = find_marker_from_cwd(str(root))
        except Exception:  # noqa: BLE001 - try the next visible root.
            continue
        if found is None:
            continue
        workspace_root, marker = found
        workspace_num = marker.workspace_num if marker.workspace_num > 0 else 1
        try:
            return artifact_ref_context(
                workspace_root,
                workspace_num,
                project=store.project_key,
            )
        except Exception:  # noqa: BLE001 - fall back to cwd-based resolution.
            return None
    return None


__all__ = [
    "ArtifactLinkDerivationInputs",
    "artifact_link_derivation_inputs",
    "derive_and_persist_artifact_links",
    "persist_derived_link_candidates",
]
