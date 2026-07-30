"""Reusable artifact-file domain and explicit-file index.

This compatibility facade preserves the public ``sase.core`` import surface
while implementation lives in focused artifact modules.
"""

from __future__ import annotations

from sase.core.artifact_file_doctor import (
    ArtifactFileBackfillReport,
    ArtifactFileDigestMismatch,
    ArtifactFileIndexInspection,
    ArtifactFileVerifyReport,
    backfill_artifact_file_index,
    inspect_artifact_file_index,
    verify_artifact_file_index,
)
from sase.core.artifact_file_defaults import (
    list_artifact_files,
    persist_default_artifact_files,
    synthesize_default_artifact_files,
)
from sase.core.artifact_file_explicit import (
    list_explicit_artifact_files,
    list_indexed_artifact_files,
    read_artifact_file_index,
    store_default_artifact_file,
    store_explicit_artifact_file,
)
from sase.core.artifact_file_types import (
    ARTIFACT_FILE_INDEX_SCHEMA_VERSION,
    ARTIFACT_FILE_INDEX_SUPPORTED_SCHEMA_VERSIONS,
    ARTIFACT_FILE_KINDS,
    ArtifactFile,
    ArtifactFileAssociation,
    ArtifactFileKind,
    artifact_file_from_dict,
    artifact_file_to_dict,
    artifact_file_association_from_dir,
    default_artifact_files_index_path,
    default_artifact_files_root,
    infer_artifact_file_kind,
)
from sase.core.artifact_file_helpers import (
    artifact_file_dedupe_key,
    artifact_file_mime_type,
)
from sase.core.artifact_file_query_facade import (
    ARTIFACT_FILE_QUERY_WIRE_SCHEMA_VERSION,
    query_artifact_files,
)
from sase.core.artifact_file_vcs import materialize_artifact_file

__all__ = [
    "ARTIFACT_FILE_INDEX_SCHEMA_VERSION",
    "ARTIFACT_FILE_INDEX_SUPPORTED_SCHEMA_VERSIONS",
    "ARTIFACT_FILE_KINDS",
    "ARTIFACT_FILE_QUERY_WIRE_SCHEMA_VERSION",
    "ArtifactFileBackfillReport",
    "ArtifactFileDigestMismatch",
    "ArtifactFileIndexInspection",
    "ArtifactFileVerifyReport",
    "ArtifactFile",
    "ArtifactFileAssociation",
    "ArtifactFileKind",
    "artifact_file_from_dict",
    "artifact_file_dedupe_key",
    "artifact_file_to_dict",
    "artifact_file_association_from_dir",
    "artifact_file_mime_type",
    "backfill_artifact_file_index",
    "default_artifact_files_index_path",
    "default_artifact_files_root",
    "infer_artifact_file_kind",
    "inspect_artifact_file_index",
    "list_artifact_files",
    "list_explicit_artifact_files",
    "list_indexed_artifact_files",
    "materialize_artifact_file",
    "persist_default_artifact_files",
    "query_artifact_files",
    "read_artifact_file_index",
    "store_default_artifact_file",
    "store_explicit_artifact_file",
    "synthesize_default_artifact_files",
    "verify_artifact_file_index",
]
