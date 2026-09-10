"""Thin Python adapter for Rust artifact-link publication ownership."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sase.core.rust import require_rust_binding

if TYPE_CHECKING:
    from sase.sdd._artifact_link_store_impl import ArtifactLinkStore


def document_kinds_for_store(store: ArtifactLinkStore) -> tuple[str, ...]:
    """Return declared document kinds, including roots that failed to resolve."""

    unresolved = getattr(store, "unresolved_document_kinds", {})
    return tuple(sorted({*store.sidecar_roots, *unresolved}))


def event_owner_requirements(
    event: Mapping[str, Any],
    document_kinds: Sequence[str],
) -> dict[str, Any]:
    """Return Rust-owned publication owner requirements for one event."""

    return dict(
        require_rust_binding("artifact_link_event_owner_requirements")(
            dict(event),
            list(document_kinds),
        )
    )


def resolved_document_roots_for_store(
    store: ArtifactLinkStore,
    requirements: Mapping[str, Any],
) -> dict[str, Path]:
    """Return resolved document roots required by one ownership result."""

    roots: dict[str, Path] = {}
    refs = requirements.get("document_refs")
    if not isinstance(refs, list):
        return roots
    for owner in refs:
        if not isinstance(owner, Mapping):
            continue
        kind = str(owner.get("kind") or "")
        if not kind:
            continue
        root = store.sidecar_roots.get(kind)
        if root is not None:
            roots[kind] = root.expanduser().resolve(strict=False)
    return roots


def publication_receipt(
    requirements: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Return Rust-owned acknowledgement decision for one publication."""

    return dict(
        require_rust_binding("artifact_link_publication_receipt")(
            dict(requirements),
            dict(evidence),
        )
    )


def publication_evidence(
    *,
    operation_id: str,
    resolved_roots: Mapping[str, Path],
    forced_roots: Sequence[Path],
    durable_roots: Sequence[Path],
    bead_owner: bool,
    bead_receipt: bool,
    local_receipt: bool,
) -> dict[str, Any]:
    """Build the JSON-shaped evidence payload expected by Rust."""

    return {
        "schema_version": int(
            require_rust_binding(
                "artifact_link_publication_ownership_wire_schema_version"
            )()
        ),
        "operation_id": operation_id,
        "resolved_roots": {
            kind: root.expanduser().resolve(strict=False).as_posix()
            for kind, root in resolved_roots.items()
        },
        "forced_roots": [
            root.expanduser().resolve(strict=False).as_posix()
            for root in dict.fromkeys(forced_roots)
        ],
        "durable_roots": [
            root.expanduser().resolve(strict=False).as_posix()
            for root in dict.fromkeys(durable_roots)
        ],
        "bead_owner": bead_owner,
        "bead_receipt": bead_receipt,
        "local_receipt": local_receipt,
    }


__all__ = [
    "document_kinds_for_store",
    "event_owner_requirements",
    "publication_evidence",
    "publication_receipt",
    "resolved_document_roots_for_store",
]
