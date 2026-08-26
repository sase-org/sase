"""Shared sidecar/bead-authority predicates for :class:`ArtifactLinkStore`."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.sdd._artifact_link_store_support import (
    BEAD_KIND,
    kind_of_ref,
    sidecar_index_path,
    writes_sidecar_json,
)


class ArtifactLinkStoreCoreMixin:
    """Predicates over sidecar ownership and bead authority."""

    sidecar_roots: Mapping[str, Path]
    beads_dir: Path | None

    def sidecar_root_for(self, artifact_ref: str) -> Path | None:
        """Return the sidecar root that should store *artifact_ref*, if any."""

        if not writes_sidecar_json(artifact_ref):
            return None
        return self.sidecar_roots.get(kind_of_ref(artifact_ref))

    def _is_aggregate_only(self, row: Mapping[str, Any]) -> bool:
        """Return whether neither endpoint owns sidecar ``links/`` JSON."""

        source = str(row.get("source_ref") or "")
        target = str(row.get("target_ref") or "")
        return (
            self.sidecar_root_for(source) is None
            and self.sidecar_root_for(target) is None
        )

    def _bead_endpoint_is_authoritative(self, row: Mapping[str, Any]) -> bool:
        """Return whether this workspace has bead truth for either endpoint.

        A bead re-derives both its outbound and inbound link events from
        its own event stream, so a bead in either endpoint position is
        proof this workspace can confirm a prior row's deletion.
        """

        if self.beads_dir is None:
            return False
        source = str(row.get("source_ref") or "")
        target = str(row.get("target_ref") or "")
        return kind_of_ref(source) == BEAD_KIND or kind_of_ref(target) == BEAD_KIND

    def _sidecar_truth_was_consulted(self, row: Mapping[str, Any]) -> bool:
        """Return whether a visible companion index can prove row deletion."""

        for ref in (str(row.get("source_ref") or ""), str(row.get("target_ref") or "")):
            root = self.sidecar_root_for(ref)
            if root is not None and sidecar_index_path(root, ref).is_file():
                return True
        return False

    def _authoritative_source_was_consulted(self, row: Mapping[str, Any]) -> bool:
        """Return whether a missing prior row is proven deleted here."""

        return self._bead_endpoint_is_authoritative(row) or (
            self._sidecar_truth_was_consulted(row)
        )
