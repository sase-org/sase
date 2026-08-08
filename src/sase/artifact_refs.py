"""Public Python facade for kind-tagged artifact references.

Rust owns the reference grammar, canonicalization, scanning, and resolution.
The focused ``artifact_ref_*`` modules own the Python context and projections;
this module preserves the original stable import surface for callers.
"""

from sase.artifact_ref_context import (
    ARTIFACT_REF_LSP_CATALOG_SCHEMA_VERSION,
    artifact_ref_context,
    artifact_ref_lsp_catalog_payload,
    launch_artifact_ref_context,
)
from sase.artifact_ref_entries import (
    design_reference_for_plan_row,
    reference_for_agent_name,
    reference_for_entry_target,
)
from sase.artifact_ref_lists import (
    ARTIFACT_REF_LIST_RESOLUTION_WIRE_SCHEMA_VERSION,
    ArtifactRefListEntry,
    artifact_ref_list_display_lines,
    normalize_artifact_ref_list,
    resolve_artifact_ref_list,
)
from sase.artifact_ref_models import (
    ARTIFACT_REF_CONTEXT_WIRE_SCHEMA_VERSION,
    ARTIFACT_REF_WIRE_SCHEMA_VERSION,
    BUILTIN_ARTIFACT_REF_KINDS,
    ArtifactRef,
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefFragment,
    ArtifactRefPayload,
    ArtifactRefProject,
    ArtifactRefPromptCandidate,
    ArtifactRefRepository,
    ArtifactRefResolution,
    ArtifactRefResolutionStatus,
    ArtifactRefSpan,
    ParsedArtifactRef,
)
from sase.artifact_ref_operations import (
    at_reference_context,
    at_reference_inventory,
    at_reference_menu,
    canonicalize_artifact_ref,
    parse_artifact_ref,
    render_artifact_ref,
    resolve_artifact_ref,
    scan_artifact_ref_prompt,
    scan_artifact_refs,
)
from sase.artifact_ref_prompt import (
    artifact_ref_resolution_hint,
    process_artifact_references,
    validate_artifact_references,
)


__all__ = [
    "ARTIFACT_REF_CONTEXT_WIRE_SCHEMA_VERSION",
    "ARTIFACT_REF_LIST_RESOLUTION_WIRE_SCHEMA_VERSION",
    "ARTIFACT_REF_LSP_CATALOG_SCHEMA_VERSION",
    "ARTIFACT_REF_WIRE_SCHEMA_VERSION",
    "BUILTIN_ARTIFACT_REF_KINDS",
    "ArtifactRef",
    "ArtifactRefAgentOwner",
    "ArtifactRefAgentRoot",
    "ArtifactRefBeadStore",
    "ArtifactRefContext",
    "ArtifactRefDocumentRoot",
    "ArtifactRefFragment",
    "ArtifactRefListEntry",
    "ArtifactRefPayload",
    "ArtifactRefProject",
    "ArtifactRefPromptCandidate",
    "ArtifactRefRepository",
    "ArtifactRefResolution",
    "ArtifactRefResolutionStatus",
    "ArtifactRefSpan",
    "ParsedArtifactRef",
    "artifact_ref_context",
    "artifact_ref_list_display_lines",
    "artifact_ref_lsp_catalog_payload",
    "artifact_ref_resolution_hint",
    "at_reference_context",
    "at_reference_inventory",
    "at_reference_menu",
    "canonicalize_artifact_ref",
    "design_reference_for_plan_row",
    "launch_artifact_ref_context",
    "normalize_artifact_ref_list",
    "parse_artifact_ref",
    "process_artifact_references",
    "reference_for_agent_name",
    "reference_for_entry_target",
    "render_artifact_ref",
    "resolve_artifact_ref",
    "resolve_artifact_ref_list",
    "scan_artifact_ref_prompt",
    "scan_artifact_refs",
    "validate_artifact_references",
]
