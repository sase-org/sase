"""Wire records for the unified artifact graph facade.

These dataclasses mirror the Epic 1 Rust wire records in
``sase_core::artifact::wire``. They are intentionally plain JSON-shaped
records: all keys are lowercase ``snake_case``, optional values are preserved
as ``None``/JSON ``null``, and sequence fields serialize as JSON lists.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from dataclasses import dataclass, field
from typing import Any

ARTIFACT_WIRE_SCHEMA_VERSION = 1

ARTIFACT_ROOT_ID = "/"

ARTIFACT_KIND_ROOT = "root"
ARTIFACT_KIND_FILE = "file"
ARTIFACT_KIND_DIRECTORY = "directory"
ARTIFACT_KIND_PROJECT = "project"
ARTIFACT_KIND_CHANGESPEC = "changespec"
ARTIFACT_KIND_COMMIT = "commit"
ARTIFACT_KIND_BEAD = "bead"
ARTIFACT_KIND_AGENT = "agent"
ARTIFACT_KIND_THOUGHT = "thought"
ARTIFACT_KIND_UNKNOWN = "unknown"

ARTIFACT_LINK_PARENT = "parent"
ARTIFACT_LINK_CREATED = "created"
ARTIFACT_LINK_WORKER = "worker"
ARTIFACT_LINK_RELATED = "related"

ARTIFACT_PROVENANCE_MANUAL = "manual"
ARTIFACT_PROVENANCE_DERIVED = "derived"

ARTIFACT_TOMBSTONE_NODE = "node"
ARTIFACT_TOMBSTONE_LINK = "link"


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


# pyvision: public_api_methods.txt
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


# pyvision: public_api_methods.txt
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
class ArtifactQueryWire:
    schema_version: int = ARTIFACT_WIRE_SCHEMA_VERSION
    text: str | None = None
    kinds: tuple[str, ...] = ()
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


# pyvision: public_api_methods.txt
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


def artifact_wire_to_json_dict(record: Any) -> Any:
    """Project artifact wire data to a JSON-safe dict/list shape."""
    if is_dataclass(record) and not isinstance(record, type):
        return {
            field_info.name: artifact_wire_to_json_dict(
                getattr(record, field_info.name)
            )
            for field_info in fields(record)
        }
    if isinstance(record, (list, tuple)):
        return [artifact_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {
            str(key): artifact_wire_to_json_dict(value) for key, value in record.items()
        }
    return record


def artifact_query_to_dict(query: ArtifactQueryWire) -> dict[str, Any]:
    return artifact_wire_to_json_dict(query)


def artifact_graph_options_to_dict(
    options: ArtifactGraphOptionsWire,
) -> dict[str, Any]:
    return artifact_wire_to_json_dict(options)


def artifact_doctor_options_to_dict(
    options: ArtifactDoctorOptionsWire,
) -> dict[str, Any]:
    return artifact_wire_to_json_dict(options)


def _check_keys(
    data: dict[str, Any],
    allowed: set[str],
    wire_name: str,
) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise TypeError(f"unknown {wire_name} field(s): {', '.join(sorted(unknown))}")


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _tuple_strs(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in (value or ()))


def artifact_node_from_dict(data: dict[str, Any]) -> ArtifactNodeWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactNodeWire)},
        "ArtifactNodeWire",
    )
    return ArtifactNodeWire(
        id=str(data["id"]),
        kind=str(data["kind"]),
        display_title=str(data["display_title"]),
        subtitle=data.get("subtitle"),
        provenance=str(data.get("provenance", ARTIFACT_PROVENANCE_MANUAL)),
        source_kind=data.get("source_kind"),
        source_id=data.get("source_id"),
        source_version=data.get("source_version"),
        search_text=str(data.get("search_text", "")),
        metadata=dict(data.get("metadata") or {}),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


# pyvision: public_api_methods.txt
def artifact_link_from_dict(data: dict[str, Any]) -> ArtifactLinkWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactLinkWire)},
        "ArtifactLinkWire",
    )
    return ArtifactLinkWire(
        id=str(data["id"]),
        link_type=str(data["link_type"]),
        source_id=str(data["source_id"]),
        target_id=str(data["target_id"]),
        provenance=str(data.get("provenance", ARTIFACT_PROVENANCE_MANUAL)),
        source_kind=data.get("source_kind"),
        source_id_hint=data.get("source_id_hint"),
        source_version=data.get("source_version"),
        metadata=dict(data.get("metadata") or {}),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


# pyvision: public_api_methods.txt
def artifact_payload_from_dict(data: dict[str, Any]) -> ArtifactPayloadWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactPayloadWire)},
        "ArtifactPayloadWire",
    )
    return ArtifactPayloadWire(
        artifact_id=str(data["artifact_id"]),
        payload_type=str(data["payload_type"]),
        provenance=str(data.get("provenance", ARTIFACT_PROVENANCE_MANUAL)),
        source_kind=data.get("source_kind"),
        source_id=data.get("source_id"),
        source_version=data.get("source_version"),
        payload=data.get("payload"),
        updated_at=data.get("updated_at"),
    )


# pyvision: public_api_methods.txt
def artifact_doctor_issue_from_dict(data: dict[str, Any]) -> ArtifactDoctorIssueWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactDoctorIssueWire)},
        "ArtifactDoctorIssueWire",
    )
    return ArtifactDoctorIssueWire(
        issue_type=str(data["issue_type"]),
        severity=str(data["severity"]),
        artifact_id=data.get("artifact_id"),
        link_id=data.get("link_id"),
        message=str(data.get("message", "")),
    )


def artifact_detail_from_dict(data: dict[str, Any]) -> ArtifactDetailWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactDetailWire)},
        "ArtifactDetailWire",
    )
    node = data.get("node")
    return ArtifactDetailWire(
        schema_version=int(data["schema_version"]),
        node=artifact_node_from_dict(node) if isinstance(node, dict) else None,
        payloads=[
            artifact_payload_from_dict(payload)
            for payload in data.get("payloads") or []
        ],
        outbound_links=[
            artifact_link_from_dict(link) for link in data.get("outbound_links") or []
        ],
        inbound_links=[
            artifact_link_from_dict(link) for link in data.get("inbound_links") or []
        ],
        children=[
            artifact_node_from_dict(child) for child in data.get("children") or []
        ],
        path_to_root=[
            artifact_node_from_dict(node) for node in data.get("path_to_root") or []
        ],
        diagnostics=[
            artifact_doctor_issue_from_dict(issue)
            for issue in data.get("diagnostics") or []
        ],
    )


# pyvision: public_api_methods.txt
def artifact_query_from_dict(data: dict[str, Any]) -> ArtifactQueryWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactQueryWire)},
        "ArtifactQueryWire",
    )
    return ArtifactQueryWire(
        schema_version=int(data.get("schema_version", ARTIFACT_WIRE_SCHEMA_VERSION)),
        text=data.get("text"),
        kinds=_tuple_strs(data.get("kinds")),
        link_types=_tuple_strs(data.get("link_types")),
        provenance=data.get("provenance"),
        source_kinds=_tuple_strs(data.get("source_kinds")),
        source_ids=_tuple_strs(data.get("source_ids")),
        root_id=data.get("root_id"),
        include_tombstoned=bool(data.get("include_tombstoned", False)),
        limit=_optional_int(data.get("limit", 200)),
        offset=_optional_int(data.get("offset", 0)),
    )


def artifact_graph_from_dict(data: dict[str, Any]) -> ArtifactGraphWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactGraphWire)},
        "ArtifactGraphWire",
    )
    return ArtifactGraphWire(
        schema_version=int(data["schema_version"]),
        root_id=data.get("root_id"),
        nodes=[artifact_node_from_dict(node) for node in data.get("nodes") or []],
        links=[artifact_link_from_dict(link) for link in data.get("links") or []],
        node_count=int(data["node_count"]),
        link_count=int(data["link_count"]),
        truncated=bool(data["truncated"]),
        limit=_optional_int(data.get("limit")),
    )


# pyvision: public_api_methods.txt
def artifact_graph_options_from_dict(
    data: dict[str, Any],
) -> ArtifactGraphOptionsWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactGraphOptionsWire)},
        "ArtifactGraphOptionsWire",
    )
    return ArtifactGraphOptionsWire(
        schema_version=int(data.get("schema_version", ARTIFACT_WIRE_SCHEMA_VERSION)),
        root_id=data.get("root_id", ARTIFACT_ROOT_ID),
        max_depth=_optional_int(data.get("max_depth", 2)),
        link_types=_tuple_strs(data.get("link_types")),
        include_inbound=bool(data.get("include_inbound", False)),
        include_outbound=bool(data.get("include_outbound", True)),
        full_graph=bool(data.get("full_graph", False)),
        limit=_optional_int(data.get("limit", 500)),
    )


# pyvision: public_api_methods.txt
def artifact_node_upsert_from_dict(data: dict[str, Any]) -> ArtifactNodeUpsertWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactNodeUpsertWire)},
        "ArtifactNodeUpsertWire",
    )
    return ArtifactNodeUpsertWire(
        schema_version=int(data["schema_version"]),
        node=artifact_node_from_dict(data["node"]),
        replace_payloads=bool(data.get("replace_payloads", False)),
    )


# pyvision: public_api_methods.txt
def artifact_node_remove_from_dict(data: dict[str, Any]) -> ArtifactNodeRemoveWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactNodeRemoveWire)},
        "ArtifactNodeRemoveWire",
    )
    return ArtifactNodeRemoveWire(
        schema_version=int(data["schema_version"]),
        id=str(data["id"]),
        provenance=data.get("provenance"),
        source_kind=data.get("source_kind"),
        source_id=data.get("source_id"),
        reason=data.get("reason"),
    )


# pyvision: public_api_methods.txt
def artifact_link_upsert_from_dict(data: dict[str, Any]) -> ArtifactLinkUpsertWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactLinkUpsertWire)},
        "ArtifactLinkUpsertWire",
    )
    return ArtifactLinkUpsertWire(
        schema_version=int(data["schema_version"]),
        link=artifact_link_from_dict(data["link"]),
    )


# pyvision: public_api_methods.txt
def artifact_link_remove_from_dict(data: dict[str, Any]) -> ArtifactLinkRemoveWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactLinkRemoveWire)},
        "ArtifactLinkRemoveWire",
    )
    return ArtifactLinkRemoveWire(
        schema_version=int(data["schema_version"]),
        id=data.get("id"),
        link_type=data.get("link_type"),
        source_id=data.get("source_id"),
        target_id=data.get("target_id"),
        provenance=data.get("provenance"),
        source_kind=data.get("source_kind"),
        source_id_hint=data.get("source_id_hint"),
        reason=data.get("reason"),
    )


def artifact_mutation_result_from_dict(
    data: dict[str, Any],
) -> ArtifactMutationResultWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactMutationResultWire)},
        "ArtifactMutationResultWire",
    )
    return ArtifactMutationResultWire(
        schema_version=int(data["schema_version"]),
        operation=str(data["operation"]),
        nodes_added=int(data.get("nodes_added", 0)),
        nodes_updated=int(data.get("nodes_updated", 0)),
        nodes_removed=int(data.get("nodes_removed", 0)),
        links_added=int(data.get("links_added", 0)),
        links_updated=int(data.get("links_updated", 0)),
        links_removed=int(data.get("links_removed", 0)),
        tombstones_added=int(data.get("tombstones_added", 0)),
        affected_node_ids=[str(item) for item in data.get("affected_node_ids") or []],
        affected_link_ids=[str(item) for item in data.get("affected_link_ids") or []],
        tombstone_ids=[str(item) for item in data.get("tombstone_ids") or []],
        errors=[str(item) for item in data.get("errors") or []],
    )


# pyvision: public_api_methods.txt
def artifact_doctor_options_from_dict(
    data: dict[str, Any],
) -> ArtifactDoctorOptionsWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactDoctorOptionsWire)},
        "ArtifactDoctorOptionsWire",
    )
    return ArtifactDoctorOptionsWire(
        schema_version=int(data.get("schema_version", ARTIFACT_WIRE_SCHEMA_VERSION)),
        check_dangling_links=bool(data.get("check_dangling_links", True)),
        check_root_presence=bool(data.get("check_root_presence", True)),
        check_reachability=bool(data.get("check_reachability", True)),
        check_duplicate_parents=bool(data.get("check_duplicate_parents", True)),
        check_tombstones=bool(data.get("check_tombstones", True)),
    )


def artifact_doctor_from_dict(data: dict[str, Any]) -> ArtifactDoctorWire:
    _check_keys(
        data,
        {field_info.name for field_info in fields(ArtifactDoctorWire)},
        "ArtifactDoctorWire",
    )
    return ArtifactDoctorWire(
        schema_version=int(data["schema_version"]),
        ok=bool(data["ok"]),
        issues=[
            artifact_doctor_issue_from_dict(issue) for issue in data.get("issues") or []
        ],
    )


__all__ = [
    "ARTIFACT_KIND_AGENT",
    "ARTIFACT_KIND_BEAD",
    "ARTIFACT_KIND_CHANGESPEC",
    "ARTIFACT_KIND_COMMIT",
    "ARTIFACT_KIND_DIRECTORY",
    "ARTIFACT_KIND_FILE",
    "ARTIFACT_KIND_PROJECT",
    "ARTIFACT_KIND_ROOT",
    "ARTIFACT_KIND_THOUGHT",
    "ARTIFACT_KIND_UNKNOWN",
    "ARTIFACT_LINK_CREATED",
    "ARTIFACT_LINK_PARENT",
    "ARTIFACT_LINK_RELATED",
    "ARTIFACT_LINK_WORKER",
    "ARTIFACT_PROVENANCE_DERIVED",
    "ARTIFACT_PROVENANCE_MANUAL",
    "ARTIFACT_ROOT_ID",
    "ARTIFACT_TOMBSTONE_LINK",
    "ARTIFACT_TOMBSTONE_NODE",
    "ARTIFACT_WIRE_SCHEMA_VERSION",
    "ArtifactDetailWire",
    "ArtifactDoctorIssueWire",
    "ArtifactDoctorOptionsWire",
    "ArtifactDoctorWire",
    "ArtifactGraphOptionsWire",
    "ArtifactGraphWire",
    "ArtifactLinkRemoveWire",
    "ArtifactLinkUpsertWire",
    "ArtifactLinkWire",
    "ArtifactMutationResultWire",
    "ArtifactNodeRemoveWire",
    "ArtifactNodeUpsertWire",
    "ArtifactNodeWire",
    "ArtifactPayloadWire",
    "ArtifactQueryWire",
    "artifact_detail_from_dict",
    "artifact_doctor_from_dict",
    "artifact_doctor_options_from_dict",
    "artifact_doctor_options_to_dict",
    "artifact_graph_from_dict",
    "artifact_graph_options_from_dict",
    "artifact_graph_options_to_dict",
    "artifact_link_from_dict",
    "artifact_link_remove_from_dict",
    "artifact_link_upsert_from_dict",
    "artifact_mutation_result_from_dict",
    "artifact_node_from_dict",
    "artifact_node_remove_from_dict",
    "artifact_node_upsert_from_dict",
    "artifact_payload_from_dict",
    "artifact_query_from_dict",
    "artifact_query_to_dict",
    "artifact_root_node",
    "artifact_wire_to_json_dict",
]
