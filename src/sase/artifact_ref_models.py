"""Public model facade for kind-tagged artifact references."""

from sase.artifact_ref_context_models import (
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefContext,
    ArtifactRefDocumentExpansion,
    ArtifactRefDocumentRoot,
    ArtifactRefFileRoot,
    ArtifactRefProject,
    ArtifactRefRepository,
)
from sase.artifact_ref_entry_models import ArtifactEntry, ArtifactEntryOrigin
from sase.artifact_ref_parsed_models import (
    ArtifactRef,
    ArtifactRefFragment,
    ArtifactRefPayload,
    ParsedArtifactRef,
)
from sase.artifact_ref_resolution_models import (
    ArtifactRefPathFilterResult,
    ArtifactRefResolution,
)
from sase.artifact_ref_scan_models import (
    ArtifactRefDocumentScan,
    ArtifactRefDocumentTarget,
    ArtifactRefPromptCandidate,
    ArtifactRefSpan,
)
from sase.artifact_ref_target_models import (
    ArtifactRefDocumentOwner,
    ArtifactRefTargetCandidate,
    ArtifactRefTargetResolution,
)
from sase.artifact_ref_wire import (
    ARTIFACT_REF_CONTEXT_WIRE_SCHEMA_VERSION,
    ARTIFACT_REF_DOCUMENT_SCAN_WIRE_SCHEMA_VERSION,
    ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION,
    ARTIFACT_REF_TARGET_RESOLUTION_WIRE_SCHEMA_VERSION,
    ARTIFACT_REF_WIRE_SCHEMA_VERSION,
    ArtifactRefDocumentTargetKind,
    ArtifactRefFragmentType,
    ArtifactRefKindType,
    ArtifactRefPayloadType,
    ArtifactRefResolutionStatus,
    ArtifactRefTargetFailureCategory,
    check_document_scan_record_schema as _check_document_scan_record_schema,
    check_record_schema,
    optional_int as _optional_int,
    optional_str,
)


__all__ = [
    "ARTIFACT_REF_CONTEXT_WIRE_SCHEMA_VERSION",
    "ARTIFACT_REF_DOCUMENT_SCAN_WIRE_SCHEMA_VERSION",
    "ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION",
    "ARTIFACT_REF_TARGET_RESOLUTION_WIRE_SCHEMA_VERSION",
    "ARTIFACT_REF_WIRE_SCHEMA_VERSION",
    "ArtifactEntry",
    "ArtifactEntryOrigin",
    "ArtifactRef",
    "ArtifactRefAgentOwner",
    "ArtifactRefAgentRoot",
    "ArtifactRefBeadStore",
    "ArtifactRefContext",
    "ArtifactRefDocumentExpansion",
    "ArtifactRefDocumentOwner",
    "ArtifactRefDocumentRoot",
    "ArtifactRefDocumentScan",
    "ArtifactRefDocumentTarget",
    "ArtifactRefDocumentTargetKind",
    "ArtifactRefFileRoot",
    "ArtifactRefFragment",
    "ArtifactRefFragmentType",
    "ArtifactRefKindType",
    "ArtifactRefPathFilterResult",
    "ArtifactRefPayload",
    "ArtifactRefPayloadType",
    "ArtifactRefProject",
    "ArtifactRefPromptCandidate",
    "ArtifactRefRepository",
    "ArtifactRefResolution",
    "ArtifactRefResolutionStatus",
    "ArtifactRefSpan",
    "ArtifactRefTargetCandidate",
    "ArtifactRefTargetFailureCategory",
    "ArtifactRefTargetResolution",
    "ParsedArtifactRef",
    "_check_document_scan_record_schema",
    "_optional_int",
    "check_record_schema",
    "optional_str",
]
