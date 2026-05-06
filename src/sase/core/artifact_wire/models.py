"""Dataclass records for the unified artifact graph wire contract.

These dataclasses mirror the Epic 1 Rust wire records in
``sase_core::artifact::wire``. They are intentionally plain JSON-shaped
records: all keys are lowercase ``snake_case``, optional values are preserved
as ``None``/JSON ``null``, and sequence fields serialize as JSON lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.core.artifact_wire.constants import (
    ARTIFACT_KIND_ROOT,
    ARTIFACT_PROVENANCE_MANUAL,
    ARTIFACT_ROOT_ID,
    ARTIFACT_STALE_CLEANUP_NONE,
    ARTIFACT_WIRE_SCHEMA_VERSION,
)


@dataclass(frozen=True)
class ArtifactNodeWire:
    id: str
    kind: str
    display_title: str
    subtitle: str | None = None
    provenance: str = ARTIFACT_PROVENANCE_MANUAL
    source_kind: str | None = None
    source_id: str | None = None
    source_version: str | None = None
    search_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ArtifactLinkWire:
    id: str
    link_type: str
    source_id: str
    target_id: str
    provenance: str = ARTIFACT_PROVENANCE_MANUAL
    source_kind: str | None = None
    source_id_hint: str | None = None
    source_version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ArtifactPayloadWire:
    artifact_id: str
    payload_type: str
    provenance: str = ARTIFACT_PROVENANCE_MANUAL
    source_kind: str | None = None
    source_id: str | None = None
    source_version: str | None = None
    payload: Any = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ArtifactRebuildRequestWire:
    schema_version: int = ARTIFACT_WIRE_SCHEMA_VERSION
    projects_root: str | None = None
    workspace_root: str | None = None
    beads_dir: str | None = None
    include_sources: tuple[str, ...] = ()
    exclude_sources: tuple[str, ...] = ()
    target_path: str | None = None
    artifact_dir: str | None = None
    stale_cleanup: str = ARTIFACT_STALE_CLEANUP_NONE


@dataclass(frozen=True)
class ArtifactPathUpsertRequestWire:
    schema_version: int = ARTIFACT_WIRE_SCHEMA_VERSION
    kind: str | None = None
    display_title: str | None = None
    subtitle: str | None = None
    provenance: str | None = None
    source_kind: str | None = None
    source_id: str | None = None
    source_version: str | None = None
    search_text: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ArtifactDoctorIssueWire:
    issue_type: str
    severity: str
    artifact_id: str | None = None
    link_id: str | None = None
    message: str = ""


@dataclass(frozen=True)
class ArtifactDetailWire:
    schema_version: int
    node: ArtifactNodeWire | None = None
    payloads: list[ArtifactPayloadWire] = field(default_factory=list)
    outbound_links: list[ArtifactLinkWire] = field(default_factory=list)
    inbound_links: list[ArtifactLinkWire] = field(default_factory=list)
    children: list[ArtifactNodeWire] = field(default_factory=list)
    path_to_root: list[ArtifactNodeWire] = field(default_factory=list)
    diagnostics: list[ArtifactDoctorIssueWire] = field(default_factory=list)


@dataclass(frozen=True)
class ArtifactPageRequestWire:
    schema_version: int = ARTIFACT_WIRE_SCHEMA_VERSION
    group_key: str | None = None
    relation: str | None = None
    link_type: str | None = None
    offset: int = 0
    limit: int = 10


@dataclass(frozen=True)
class ArtifactGroupSummaryWire:
    group_key: str
    direction: str
    link_type: str | None = None
    total_count: int = 0
    loaded_count: int = 0


@dataclass(frozen=True)
class ArtifactRelationPageWire:
    summary: ArtifactGroupSummaryWire
    nodes: list[ArtifactNodeWire] = field(default_factory=list)
    links: list[ArtifactLinkWire] = field(default_factory=list)


@dataclass(frozen=True)
class ArtifactTypeCountWire:
    artifact_type: str
    total_count: int


@dataclass(frozen=True)
class ArtifactSummaryRequestWire:
    schema_version: int = ARTIFACT_WIRE_SCHEMA_VERSION
    artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactSummaryWire:
    artifact_id: str
    state: str
    total_linked_count: int = 0
    file_type_counts: list[ArtifactTypeCountWire] = field(default_factory=list)
    kind_counts: list[ArtifactTypeCountWire] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class ArtifactDetailPagedWire:
    schema_version: int
    node: ArtifactNodeWire | None = None
    payloads: list[ArtifactPayloadWire] = field(default_factory=list)
    path_to_root: list[ArtifactNodeWire] = field(default_factory=list)
    diagnostics: list[ArtifactDoctorIssueWire] = field(default_factory=list)
    children_page: ArtifactRelationPageWire | None = None
    outbound_pages: list[ArtifactRelationPageWire] = field(default_factory=list)
    inbound_pages: list[ArtifactRelationPageWire] = field(default_factory=list)
    type_counts: list[ArtifactTypeCountWire] = field(default_factory=list)


@dataclass(frozen=True)
class ArtifactQueryWire:
    schema_version: int = ARTIFACT_WIRE_SCHEMA_VERSION
    text: str | None = None
    kinds: tuple[str, ...] = ()
    file_types: tuple[str, ...] = ()
    link_types: tuple[str, ...] = ()
    provenance: str | None = None
    source_kinds: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    root_id: str | None = None
    include_tombstoned: bool = False
    limit: int | None = 200
    offset: int | None = 0


@dataclass(frozen=True)
class ArtifactGraphWire:
    schema_version: int
    root_id: str | None = None
    nodes: list[ArtifactNodeWire] = field(default_factory=list)
    links: list[ArtifactLinkWire] = field(default_factory=list)
    node_count: int = 0
    link_count: int = 0
    truncated: bool = False
    limit: int | None = None


@dataclass(frozen=True)
class ArtifactGraphOptionsWire:
    schema_version: int = ARTIFACT_WIRE_SCHEMA_VERSION
    root_id: str | None = ARTIFACT_ROOT_ID
    max_depth: int | None = 2
    link_types: tuple[str, ...] = ()
    include_inbound: bool = False
    include_outbound: bool = True
    full_graph: bool = False
    limit: int | None = 500


@dataclass(frozen=True)
class ArtifactNodeUpsertWire:
    schema_version: int
    node: ArtifactNodeWire
    replace_payloads: bool = False


@dataclass(frozen=True)
class ArtifactNodeRemoveWire:
    schema_version: int
    id: str
    provenance: str | None = None
    source_kind: str | None = None
    source_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ArtifactLinkUpsertWire:
    schema_version: int
    link: ArtifactLinkWire


@dataclass(frozen=True)
class ArtifactLinkRemoveWire:
    schema_version: int
    id: str | None = None
    link_type: str | None = None
    source_id: str | None = None
    target_id: str | None = None
    provenance: str | None = None
    source_kind: str | None = None
    source_id_hint: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ArtifactMutationResultWire:
    schema_version: int
    operation: str
    nodes_added: int = 0
    nodes_updated: int = 0
    nodes_removed: int = 0
    links_added: int = 0
    links_updated: int = 0
    links_removed: int = 0
    tombstones_added: int = 0
    affected_node_ids: list[str] = field(default_factory=list)
    affected_link_ids: list[str] = field(default_factory=list)
    tombstone_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ArtifactDoctorOptionsWire:
    schema_version: int = ARTIFACT_WIRE_SCHEMA_VERSION
    check_dangling_links: bool = True
    check_root_presence: bool = True
    check_reachability: bool = True
    check_duplicate_parents: bool = True
    check_tombstones: bool = True


@dataclass(frozen=True)
class ArtifactDoctorWire:
    schema_version: int
    ok: bool
    issues: list[ArtifactDoctorIssueWire] = field(default_factory=list)


def artifact_root_node() -> ArtifactNodeWire:
    """Return the canonical root artifact node."""
    return ArtifactNodeWire(
        id=ARTIFACT_ROOT_ID,
        kind=ARTIFACT_KIND_ROOT,
        display_title=ARTIFACT_ROOT_ID,
        subtitle="Artifact root",
        provenance=ARTIFACT_PROVENANCE_MANUAL,
        search_text="root /",
    )


__all__ = [
    "ArtifactDetailPagedWire",
    "ArtifactDetailWire",
    "ArtifactDoctorIssueWire",
    "ArtifactDoctorOptionsWire",
    "ArtifactDoctorWire",
    "ArtifactGraphOptionsWire",
    "ArtifactGraphWire",
    "ArtifactGroupSummaryWire",
    "ArtifactLinkRemoveWire",
    "ArtifactLinkUpsertWire",
    "ArtifactLinkWire",
    "ArtifactMutationResultWire",
    "ArtifactNodeRemoveWire",
    "ArtifactNodeUpsertWire",
    "ArtifactNodeWire",
    "ArtifactPageRequestWire",
    "ArtifactPathUpsertRequestWire",
    "ArtifactPayloadWire",
    "ArtifactQueryWire",
    "ArtifactRelationPageWire",
    "ArtifactRebuildRequestWire",
    "ArtifactSummaryRequestWire",
    "ArtifactSummaryWire",
    "ArtifactTypeCountWire",
    "artifact_root_node",
]
