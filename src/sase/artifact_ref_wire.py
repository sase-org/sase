"""Shared wire constants and coercion helpers for artifact-reference models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast


ARTIFACT_REF_WIRE_SCHEMA_VERSION = 5
ARTIFACT_REF_CONTEXT_WIRE_SCHEMA_VERSION = 2
ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION = 1
ARTIFACT_REF_DOCUMENT_SCAN_WIRE_SCHEMA_VERSION = 1
ARTIFACT_REF_TARGET_RESOLUTION_WIRE_SCHEMA_VERSION = 1

ArtifactRefKindType = Literal[
    "commit",
    "chat",
    "bug",
    "file",
    "bead",
    "agent",
    "stitch",
    "patch",
    "document",
]
ArtifactRefPayloadType = ArtifactRefKindType
ArtifactRefFragmentType = Literal["lines", "page", "time"]
ArtifactRefResolutionStatus = Literal[
    "exact",
    "drifted",
    "vcs_backed",
    "ambiguous",
    "missing",
    "unknown_kind",
    "unknown_repo",
    "unknown_project",
    "filtered",
    "denied",
]
ArtifactRefDocumentTargetKind = Literal["artifact_ref", "url", "file_path"]
ArtifactRefTargetFailureCategory = Literal[
    "missing_checkout",
    "unavailable_revision",
    "ambiguous",
    "denied_filtered",
    "temporary_error",
    "proven_missing",
]


def check_record_schema(
    raw: Mapping[str, Any],
    *,
    record: str,
) -> None:
    version = int(raw["schema_version"])
    if version != ARTIFACT_REF_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs returned an unsupported {record} wire: {version}"
        )


def check_document_scan_record_schema(
    raw: Mapping[str, Any],
    *,
    record: str,
) -> None:
    version = int(raw["schema_version"])
    if version != ARTIFACT_REF_DOCUMENT_SCAN_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs returned an unsupported {record} wire: {version}"
        )


def optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def optional_int(value: object) -> int | None:
    return None if value is None else int(cast(Any, value))


__all__ = [
    "ARTIFACT_REF_CONTEXT_WIRE_SCHEMA_VERSION",
    "ARTIFACT_REF_DOCUMENT_SCAN_WIRE_SCHEMA_VERSION",
    "ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION",
    "ARTIFACT_REF_TARGET_RESOLUTION_WIRE_SCHEMA_VERSION",
    "ARTIFACT_REF_WIRE_SCHEMA_VERSION",
    "ArtifactRefDocumentTargetKind",
    "ArtifactRefFragmentType",
    "ArtifactRefKindType",
    "ArtifactRefPayloadType",
    "ArtifactRefResolutionStatus",
    "ArtifactRefTargetFailureCategory",
    "check_document_scan_record_schema",
    "check_record_schema",
    "optional_int",
    "optional_str",
]
