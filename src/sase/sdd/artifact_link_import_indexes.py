"""Import legacy artifact-link ``links/`` indexes into immutable events."""

from __future__ import annotations

from sase.sdd._artifact_link_import_apply import (
    ArtifactLinkIndexImportReport,
    import_artifact_link_indexes,
)
from sase.sdd._artifact_link_import_plan import (
    artifact_link_legacy_links_tree_identity,
)

__all__ = [
    "ArtifactLinkIndexImportReport",
    "artifact_link_legacy_links_tree_identity",
    "import_artifact_link_indexes",
]
