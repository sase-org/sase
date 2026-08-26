"""Bounded, resumable retroactive derivation sweep over one project's store.

The reactive derivation hooks (``sase plan propose``, ``sase artifact
create``, the sidecar commit path) only see documents created or committed
after their hooks landed. This sweep covers everything that existed before
them: it walks every ``plan:``/``research:`` document the project's sidecar
roots hold, deriving and persisting candidates for whichever ones a caller has
not already swept.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import time

from sase.artifact_links.derive import (
    DerivableDocument,
    DerivedLinkCandidate,
    derive_candidate_links,
)
from sase.sdd._artifact_link_store_support import is_projected_row
from sase.sdd.artifact_link_derivation import (
    ArtifactLinkDerivationInputs,
    artifact_link_derivation_inputs,
    persist_derived_link_candidates,
)
from sase.sdd.artifact_link_store import (
    ArtifactLinkStore,
    canonicalize_artifact_link_ref,
)
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR

_SWEEP_KINDS = ("plan", "research")
_SWEEP_CREATED_BY = "sase"
_PERSIST_CHUNK_SIZE = 50


@dataclass(frozen=True)
class _ArtifactLinkBackfillReport:
    """Outcome of one bounded sweep batch."""

    total_pending: int = 0
    scanned: int = 0
    candidates: int = 0
    persisted: int = 0
    remaining: int = 0
    errors: tuple[str, ...] = ()


def sweepable_artifact_link_documents(
    store: ArtifactLinkStore,
    *,
    already_swept: frozenset[str] = frozenset(),
) -> tuple[DerivableDocument, ...]:
    """Return every derivable document *store* holds, minus *already_swept*.

    Ordered by ref for determinism across ticks. A document whose kind's
    sidecar root is not configured for this project contributes nothing.
    """

    documents: list[DerivableDocument] = []
    for kind in _SWEEP_KINDS:
        root = store.sidecar_roots.get(kind)
        if root is None or not root.is_dir():
            continue
        resolved_root = root.expanduser().resolve(strict=False)
        for path in sorted(resolved_root.rglob("*.md")):
            relative = path.relative_to(resolved_root)
            if relative.parts[:1] == (REFERENCED_BY_LINKS_DIR,):
                continue
            ref = canonicalize_artifact_link_ref(f"{kind}:{relative.as_posix()}")
            if ref in already_swept:
                continue
            documents.append(DerivableDocument(ref=ref, path=path))
    documents.sort(key=lambda document: document.ref)
    return tuple(documents)


def run_artifact_link_backfill_batch(
    store: ArtifactLinkStore,
    *,
    already_swept: frozenset[str],
    batch_size: int,
    deadline: float | None = None,
    artifacts_dir: str | Path | None = None,
) -> tuple[_ArtifactLinkBackfillReport, frozenset[str]]:
    """Derive and persist one bounded batch of not-yet-swept documents.

    Returns the batch report plus the updated swept-ref set: *already_swept*
    plus every document this call examined, whether or not it produced a
    candidate, so a repeat call over an unchanged tree is a fast no-op.
    """

    pending = sweepable_artifact_link_documents(store, already_swept=already_swept)
    if not pending:
        return _ArtifactLinkBackfillReport(), already_swept

    batch = pending[: max(0, batch_size)]
    if not batch:
        return (
            _ArtifactLinkBackfillReport(
                total_pending=len(pending), remaining=len(pending)
            ),
            already_swept,
        )

    updated_swept = set(already_swept)
    candidates = 0
    persisted = 0
    errors: list[str] = []
    scanned = 0
    derivation_inputs = artifact_link_derivation_inputs(store)
    for offset in range(0, len(batch), _PERSIST_CHUNK_SIZE):
        chunk = batch[offset : offset + _PERSIST_CHUNK_SIZE]
        candidates_by_ref = _derive_chunk_candidates(chunk, derivation_inputs)
        chunk_candidates = tuple(
            candidate
            for document_candidates in candidates_by_ref.values()
            for candidate in document_candidates
        )
        outcome = persist_derived_link_candidates(
            store,
            chunk_candidates,
            created_by=_SWEEP_CREATED_BY,
            artifacts_dir=artifacts_dir,
        )
        scanned += len(chunk)
        candidates += len(chunk_candidates)
        persisted += outcome.persisted
        errors.extend(outcome.errors)
        updated_swept.update(
            _swept_refs_after_chunk(
                store,
                candidates_by_ref=candidates_by_ref,
                had_errors=bool(outcome.errors),
                errors=errors,
            )
        )
        if deadline is not None and time.monotonic() >= deadline:
            break
    report = _ArtifactLinkBackfillReport(
        total_pending=len(pending),
        scanned=scanned,
        candidates=candidates,
        persisted=persisted,
        remaining=sum(1 for document in pending if document.ref not in updated_swept),
        errors=tuple(errors),
    )
    return report, frozenset(updated_swept)


def _derive_chunk_candidates(
    documents: Sequence[DerivableDocument],
    derivation_inputs: ArtifactLinkDerivationInputs,
) -> dict[str, tuple[DerivedLinkCandidate, ...]]:
    return {
        document.ref: derive_candidate_links(
            (document,),
            known_bead_ids=derivation_inputs.known_bead_ids,
            agents_sidecar_root=derivation_inputs.agents_sidecar_root,
            is_agent_published=derivation_inputs.is_agent_published,
        )
        for document in documents
    }


def _swept_refs_after_chunk(
    store: ArtifactLinkStore,
    *,
    candidates_by_ref: Mapping[str, Sequence[DerivedLinkCandidate]],
    had_errors: bool,
    errors: list[str],
) -> tuple[str, ...]:
    durable_keys = _stored_link_keys(store) if not had_errors else frozenset()
    swept_refs: list[str] = []
    for ref, document_candidates in candidates_by_ref.items():
        if not document_candidates:
            swept_refs.append(ref)
            continue
        if had_errors:
            continue
        missing = [
            candidate
            for candidate in document_candidates
            if _candidate_key(candidate) not in durable_keys
        ]
        if missing:
            errors.append(f"{ref}: derived link candidates were not durable")
            continue
        swept_refs.append(ref)
    return tuple(swept_refs)


def _candidate_key(candidate: DerivedLinkCandidate) -> tuple[str, str, str]:
    return (candidate.source_ref, candidate.relation, candidate.target_ref)


def _stored_link_keys(store: ArtifactLinkStore) -> frozenset[tuple[str, str, str]]:
    return frozenset(
        (
            str(row.get("source_ref") or ""),
            str(row.get("relation") or ""),
            str(row.get("target_ref") or ""),
        )
        for row in store.load_aggregate().get("rows", [])
        if not is_projected_row(row)
    )


@dataclass(frozen=True)
class _ArtifactLinkReconcileReport:
    """Outcome of one cross-workspace reconcile-and-repair pass."""

    repaired_renames: int = 0


def reconcile_and_repair_artifact_links(
    store: ArtifactLinkStore,
) -> _ArtifactLinkReconcileReport:
    """Run the cross-workspace aggregate reconcile and dangling-ref repair.

    The aggregate reconcile writes only machine-local state
    (``~/.sase/projects/<key>/artifact-links.json``), so it needs no commit.
    The rename repair rewrites sidecar ``links/`` index files inside a
    project's plans/research git repos, so its changed paths are committed
    directly here: unlike interactive ``sase artifact doctor --fix``, no
    finalizer runs after this chop to pick up files a fix pass left dirty.
    """

    from sase.artifact_cli.link_health import dangling_and_orphaned_artifact_link_refs
    from sase.sdd._artifact_link_commit import commit_artifact_link_indexes
    from sase.sdd._artifact_link_renames import repair_historical_artifact_renames

    store.reconcile_aggregate()
    refs = dangling_and_orphaned_artifact_link_refs(store)
    repair = repair_historical_artifact_renames(store, refs)
    if repair.changed_paths:
        commit_artifact_link_indexes(
            repair.changed_paths,
            store=store.sdd_store,
            repo_roots=tuple(store.sidecar_roots.values()),
            push_after_commit="async",
            mutation_origin="machine" if store.sdd_store is not None else "user",
        )
    return _ArtifactLinkReconcileReport(repaired_renames=len(repair.renames))


__all__ = [
    "reconcile_and_repair_artifact_links",
    "run_artifact_link_backfill_batch",
    "sweepable_artifact_link_documents",
]
