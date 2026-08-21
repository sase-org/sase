"""Public API for typed artifact-link storage.

The implementation is split between the stateful store adapter and the shared
row/index persistence helpers. Keeping this module as the public facade avoids
churn for callers while giving each responsibility a smaller home.
"""

from sase.sdd._artifact_link_store_impl import (
    ArtifactLinkRemoval,
    ArtifactLinkStore,
    resolve_artifact_link_project_key,
    resolve_artifact_link_store,
)
from sase.sdd._artifact_link_store_support import (
    ARTIFACT_LINK_AGGREGATE_FILENAME,
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    NON_SIDECAR_KINDS,
    artifact_link_aggregate_path,
    assembled_artifact_relations,
    canonicalize_artifact_link_ref,
)

__all__ = [
    "ARTIFACT_LINK_AGGREGATE_FILENAME",
    "ARTIFACT_LINK_ROW_SCHEMA_VERSION",
    "NON_SIDECAR_KINDS",
    "ArtifactLinkRemoval",
    "ArtifactLinkStore",
    "artifact_link_aggregate_path",
    "assembled_artifact_relations",
    "canonicalize_artifact_link_ref",
    "resolve_artifact_link_project_key",
    "resolve_artifact_link_store",
]
