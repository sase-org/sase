"""Build artifact wire requests from parsed CLI arguments."""

from __future__ import annotations

import argparse

from sase.core.artifact_wire import (
    ARTIFACT_PROVENANCE_MANUAL,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactLinkUpsertWire,
    ArtifactLinkWire,
    ArtifactNodeUpsertWire,
    ArtifactNodeWire,
    ArtifactPayloadWire,
    ArtifactQueryWire,
)

from .common import json_object, json_value


def query_from_args(args: argparse.Namespace) -> ArtifactQueryWire:
    return ArtifactQueryWire(
        text=args.text,
        kinds=tuple(args.kind),
        file_types=tuple(args.file_type),
        link_types=tuple(args.link_type),
        provenance=args.provenance,
        source_kinds=tuple(args.source_kind),
        source_ids=tuple(args.source_id),
        root_id=args.root_id,
        include_tombstoned=args.include_tombstoned,
        limit=args.limit,
        offset=args.offset,
    )


def node_upsert_from_args(args: argparse.Namespace) -> ArtifactNodeUpsertWire:
    if not args.artifact_id:
        raise ValueError("node upsert requires -a/--artifact-id")
    if not args.kind:
        raise ValueError("node upsert requires -k/--kind")
    metadata = json_object(args.metadata_json, "metadata JSON")
    node = ArtifactNodeWire(
        id=args.artifact_id,
        kind=args.kind,
        display_title=args.title or args.artifact_id,
        subtitle=args.subtitle,
        provenance=ARTIFACT_PROVENANCE_MANUAL,
        search_text=args.search_text or "",
        metadata=metadata,
    )
    return ArtifactNodeUpsertWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=node,
    )


def payload_from_args(args: argparse.Namespace) -> ArtifactPayloadWire:
    if not args.artifact_id:
        raise ValueError("payload upsert requires -a/--artifact-id")
    if not args.payload_type:
        raise ValueError("payload upsert requires -P/--payload-type")
    if args.payload_json is None:
        raise ValueError("payload upsert requires -p/--payload-json")
    return ArtifactPayloadWire(
        artifact_id=args.artifact_id,
        payload_type=args.payload_type,
        provenance=ARTIFACT_PROVENANCE_MANUAL,
        payload=json_value(args.payload_json, "payload JSON"),
    )


def links_from_args(args: argparse.Namespace) -> list[ArtifactLinkUpsertWire]:
    links: list[ArtifactLinkUpsertWire] = []
    links.extend(_link_from_compact(spec) for spec in args.link)
    links.extend(_link_from_json(raw) for raw in args.link_json)
    return links


def _link_from_compact(spec: str) -> ArtifactLinkUpsertWire:
    parts = [part.strip() for part in spec.split("|")]
    if len(parts) == 3:
        link_id = ""
        link_type, source_id, target_id = parts
    elif len(parts) == 4:
        link_id, link_type, source_id, target_id = parts
    else:
        raise ValueError(
            "compact link must be TYPE|SOURCE_ID|TARGET_ID or ID|TYPE|SOURCE_ID|TARGET_ID"
        )
    if not link_type or not source_id or not target_id:
        raise ValueError("compact link type, source ID, and target ID are required")
    return _link_upsert(
        ArtifactLinkWire(
            id=link_id,
            link_type=link_type,
            source_id=source_id,
            target_id=target_id,
            provenance=ARTIFACT_PROVENANCE_MANUAL,
        )
    )


def _link_from_json(raw: str) -> ArtifactLinkUpsertWire:
    data = json_object(raw, "link JSON")
    metadata = data.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("link JSON metadata must be a JSON object")
    try:
        link = ArtifactLinkWire(
            id=str(data.get("id") or ""),
            link_type=str(data["link_type"]),
            source_id=str(data["source_id"]),
            target_id=str(data["target_id"]),
            provenance=str(data.get("provenance") or ARTIFACT_PROVENANCE_MANUAL),
            source_kind=_optional_str(data.get("source_kind")),
            source_id_hint=_optional_str(data.get("source_id_hint")),
            source_version=_optional_str(data.get("source_version")),
            metadata=dict(metadata),
        )
    except KeyError as exc:
        raise ValueError(f"link JSON missing required field {exc.args[0]!r}") from exc
    return _link_upsert(link)


def _link_upsert(link: ArtifactLinkWire) -> ArtifactLinkUpsertWire:
    return ArtifactLinkUpsertWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        link=link,
    )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)
