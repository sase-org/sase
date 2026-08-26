"""Stateful adapter over artifact-link sidecars, beads, and aggregates.

The implementation is split across sibling modules by storage layer (sidecar
JSON, the project aggregate, bead events, cross-workspace reconciliation) plus
this facade, which assembles :class:`ArtifactLinkStore` from mixins so each
layer stays in its own small file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sase.sdd._artifact_link_project_key import (
    resolve_artifact_link_project_key,
    resolve_artifact_link_store,
)
from sase.sdd._artifact_link_store_aggregate import ArtifactLinkStoreAggregateMixin
from sase.sdd._artifact_link_store_bead_rows import ArtifactLinkStoreBeadRowsMixin
from sase.sdd._artifact_link_store_core import ArtifactLinkStoreCoreMixin
from sase.sdd._artifact_link_store_projected import ArtifactLinkStoreProjectedMixin
from sase.sdd._artifact_link_store_reconcile import ArtifactLinkStoreReconcileMixin
from sase.sdd._artifact_link_store_rows import (
    ArtifactLinkRemoval,
    ArtifactLinkStoreRowsMixin,
)
from sase.sdd._artifact_link_store_sidecar import ArtifactLinkStoreSidecarMixin
from sase.sdd._artifact_link_store_support import (
    artifact_link_aggregate_path,
    sidecar_kind_for_role,
)
from sase.sdd.store import SddStore, document_sidecar_roles

__all__ = [
    "ArtifactLinkRemoval",
    "ArtifactLinkStore",
    "resolve_artifact_link_project_key",
    "resolve_artifact_link_store",
]


@dataclass(frozen=True)
class ArtifactLinkStore(
    ArtifactLinkStoreCoreMixin,
    ArtifactLinkStoreRowsMixin,
    ArtifactLinkStoreSidecarMixin,
    ArtifactLinkStoreAggregateMixin,
    ArtifactLinkStoreProjectedMixin,
    ArtifactLinkStoreBeadRowsMixin,
    ArtifactLinkStoreReconcileMixin,
):
    """Kind-native adapter over sidecar ``links/`` JSON plus the aggregate."""

    project_key: str
    sidecar_roots: Mapping[str, Path]
    beads_dir: Path | None = None
    sdd_store: SddStore | None = None

    def __post_init__(self) -> None:
        key = self.project_key.strip()
        artifact_link_aggregate_path(key)
        object.__setattr__(self, "project_key", key)

    @classmethod
    def from_sdd_store(cls, store: SddStore, project_key: str) -> ArtifactLinkStore:
        """Build an adapter from one resolved SDD store."""

        roots: dict[str, Path] = {}
        roles = document_sidecar_roles(store.split_sidecar_roles(), include_plans=True)
        for role in roles:
            try:
                roots[sidecar_kind_for_role(role)] = (
                    store.repo_root_for_kind(role).expanduser().resolve(strict=False)
                )
            except Exception:  # noqa: BLE001 - skip unresolved sidecars
                continue
        beads_dir = store.beads_dir
        if beads_dir is not None:
            resolved = beads_dir.expanduser().resolve(strict=False)
            beads_dir = resolved if resolved.is_dir() else None
        return cls(
            project_key=project_key,
            sidecar_roots=roots,
            beads_dir=beads_dir,
            sdd_store=store,
        )
