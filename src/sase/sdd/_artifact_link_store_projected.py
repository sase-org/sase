"""Recomputed `origin: projected` rows fed into aggregate projection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.artifact_links.projection import build_projection_inputs, project_link_rows

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


class ArtifactLinkStoreProjectedMixin:
    """Builds :class:`ProjectionInputs` strictly from this store's own roots."""

    project_key: str
    sdd_store: SddStore | None

    def projected_rows(self) -> tuple[dict[str, Any], ...]:
        """Return the rows every projection rule recomputes right now.

        Built fresh on every call from this workspace's own primary repo and
        agents sidecar -- never cross-workspace-reconciled, unlike sidecar
        and bead rows, since a projection rule reads owned facts rather than
        another workspace's writes.
        """

        inputs = build_projection_inputs(
            project_key=self.project_key, sdd_store=self.sdd_store
        )
        return project_link_rows(inputs)


__all__ = ["ArtifactLinkStoreProjectedMixin"]
