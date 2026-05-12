"""Reusable agent artifact domain and explicit-artifact index.

This compatibility facade preserves the public ``sase.core`` import surface
while implementation lives in focused artifact modules.
"""

from __future__ import annotations

from sase.core.agent_artifact_defaults import (
    list_agent_artifacts,
    persist_default_agent_artifacts,
    synthesize_default_agent_artifacts,
)
from sase.core.agent_artifact_explicit import (
    list_explicit_agent_artifacts,
    list_indexed_agent_artifacts,
    read_explicit_agent_artifact_index,
    store_default_agent_artifact,
    store_explicit_agent_artifact,
)
from sase.core.agent_artifact_types import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AGENT_ARTIFACT_KINDS,
    AgentArtifact,
    AgentArtifactAssociation,
    AgentArtifactKind,
    agent_artifact_from_dict,
    agent_artifact_to_dict,
    artifact_association_from_dir,
    default_agent_artifacts_index_path,
    default_artifacts_root,
    infer_artifact_kind,
)

__all__ = [
    "AGENT_ARTIFACT_INDEX_SCHEMA_VERSION",
    "AGENT_ARTIFACT_KINDS",
    "AgentArtifact",
    "AgentArtifactAssociation",
    "AgentArtifactKind",
    "agent_artifact_from_dict",
    "agent_artifact_to_dict",
    "artifact_association_from_dir",
    "default_agent_artifacts_index_path",
    "default_artifacts_root",
    "infer_artifact_kind",
    "list_agent_artifacts",
    "list_explicit_agent_artifacts",
    "list_indexed_agent_artifacts",
    "persist_default_agent_artifacts",
    "read_explicit_agent_artifact_index",
    "store_default_agent_artifact",
    "store_explicit_agent_artifact",
    "synthesize_default_agent_artifacts",
]
