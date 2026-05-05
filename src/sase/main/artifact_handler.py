"""Handler for ``sase artifact`` subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections.abc import Iterable
from typing import NoReturn

from sase.core import artifact_facade
from sase.core.artifact_wire import (
    ARTIFACT_ROOT_ID,
    ARTIFACT_PROVENANCE_MANUAL,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDoctorOptionsWire,
    ArtifactGraphOptionsWire,
    ArtifactLinkRemoveWire,
    ArtifactLinkUpsertWire,
    ArtifactLinkWire,
    ArtifactMutationResultWire,
    ArtifactNodeRemoveWire,
    ArtifactNodeUpsertWire,
    ArtifactNodeWire,
    ArtifactPayloadWire,
    ArtifactQueryWire,
    artifact_wire_to_json_dict,
)


def _default_artifact_index_path() -> Path:
    """Return the default unified artifact SQLite index path."""
    return Path.home() / ".sase" / "artifacts.sqlite"


def handle_artifact_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch to the appropriate artifact sub-handler."""
    sub = getattr(args, "artifact_subcommand", None)

    try:
        if sub == "add":
            _handle_add(args)
        if sub == "remove":
            _handle_remove(args)
        if sub == "list":
            _handle_list(args)
        if sub == "show":
            _handle_show(args)
        if sub == "graph":
            _handle_graph(args)
        if sub == "rebuild":
            _handle_rebuild(args)
        if sub == "doctor":
            _handle_doctor(args)
    except Exception as exc:
        print(f"sase artifact {sub or ''}: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Usage: sase artifact {add,remove,list,show,graph,rebuild,doctor}")
    sys.exit(1)


def _index_path(args: argparse.Namespace) -> Path:
    value = getattr(args, "index", None)
    if value:
        return Path(value).expanduser()
    return _default_artifact_index_path()


def _emit_json(value: object) -> NoReturn:
    print(
        json.dumps(
            artifact_wire_to_json_dict(value),
            indent=2,
            sort_keys=True,
        )
    )
    sys.exit(0)


def _emit_mutation_result(
    result: ArtifactMutationResultWire, *, json_output: bool
) -> NoReturn:
    if json_output:
        _emit_json(result)
    print(f"operation: {result.operation}")
    for label, values in (
        ("affected nodes", result.affected_node_ids),
        ("affected links", result.affected_link_ids),
        ("tombstones", result.tombstone_ids),
    ):
        if values:
            print(f"{label}: {', '.join(values)}")
    if result.errors:
        print(f"errors: {', '.join(result.errors)}")
    sys.exit(0)


def _require_json(args: argparse.Namespace, command: str) -> None:
    if not getattr(args, "json", False):
        raise ValueError(
            f"human output is not implemented yet; use `sase artifact {command} -j`"
        )


def _handle_add(args: argparse.Namespace) -> NoReturn:
    requests: list[
        ArtifactNodeUpsertWire | ArtifactPayloadWire | ArtifactLinkUpsertWire
    ] = []

    if any(
        value is not None
        for value in (
            args.kind,
            args.title,
            args.subtitle,
            args.search_text,
            args.metadata_json,
        )
    ):
        requests.append(_node_upsert_from_args(args))
    if args.payload_json is not None or args.payload_type:
        requests.append(_payload_from_args(args))
    requests.extend(_links_from_args(args))

    if not requests:
        raise ValueError(
            "add requires a node (-a/-k), payload (-a/-P/-p), or link (-l/-L)"
        )

    results = [
        artifact_facade.artifact_add(_index_path(args), request) for request in requests
    ]
    _emit_mutation_result(
        _merge_mutation_results("add", results), json_output=args.json
    )


def _handle_remove(args: argparse.Namespace) -> NoReturn:
    requests: list[ArtifactNodeRemoveWire | ArtifactLinkRemoveWire] = []
    has_link_tuple = bool(args.link_type or args.source_id or args.target_id)
    if args.artifact_id:
        if has_link_tuple or args.link_id:
            raise ValueError("remove accepts either a node selector or a link selector")
        requests.append(
            ArtifactNodeRemoveWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                id=args.artifact_id,
                provenance=args.provenance,
                reason=args.reason,
            )
        )
    elif args.link_id or has_link_tuple:
        if has_link_tuple and not (
            args.link_type and args.source_id and args.target_id
        ):
            raise ValueError(
                "link tuple removal requires -T/--link-type, -S/--source-id, and -D/--target-id"
            )
        requests.append(
            ArtifactLinkRemoveWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                id=args.link_id,
                link_type=args.link_type,
                source_id=args.source_id,
                target_id=args.target_id,
                provenance=args.provenance,
                reason=args.reason,
            )
        )
    else:
        raise ValueError(
            "remove requires -a/--artifact-id, -l/--link-id, or a link tuple"
        )

    results = [
        artifact_facade.artifact_remove(_index_path(args), request)
        for request in requests
    ]
    _emit_mutation_result(
        _merge_mutation_results("remove", results),
        json_output=args.json,
    )


def _handle_list(args: argparse.Namespace) -> NoReturn:
    _require_json(args, "list")
    query = ArtifactQueryWire(
        text=args.text,
        kinds=tuple(args.kind),
        link_types=tuple(args.link_type),
        provenance=args.provenance,
        source_kinds=tuple(args.source_kind),
        source_ids=tuple(args.source_id),
        root_id=args.root_id,
        include_tombstoned=args.include_tombstoned,
        limit=args.limit,
        offset=args.offset,
    )
    _emit_json(artifact_facade.artifact_list(_index_path(args), query))


def _handle_show(args: argparse.Namespace) -> NoReturn:
    _require_json(args, "show")
    _emit_json(artifact_facade.artifact_show(_index_path(args), args.artifact_id))


def _handle_graph(args: argparse.Namespace) -> NoReturn:
    output_format = "json" if args.json else args.format
    if output_format != "json":
        raise ValueError("only JSON graph output is implemented yet; use `-f json`")
    options = ArtifactGraphOptionsWire(
        root_id=args.artifact_id if args.artifact_id else ARTIFACT_ROOT_ID,
        max_depth=args.depth,
        link_types=tuple(args.link_type),
        include_inbound=args.include_inbound,
        include_outbound=args.include_outbound,
        full_graph=args.full,
        limit=args.limit,
    )
    _emit_json(artifact_facade.artifact_graph(_index_path(args), options))


def _handle_rebuild(args: argparse.Namespace) -> NoReturn:
    _require_json(args, "rebuild")
    request = artifact_facade.artifact_rebuild_request(
        projects_root=args.projects_root,
        workspace_root=args.workspace_root,
        beads_dir=args.beads_dir,
        include_sources=tuple(args.include_source),
        exclude_sources=tuple(args.exclude_source),
        target_path=args.target_path,
        artifact_dir=args.artifact_dir,
        stale_cleanup=args.stale_cleanup,
    )
    _emit_json(artifact_facade.artifact_rebuild(_index_path(args), request))


def _handle_doctor(args: argparse.Namespace) -> NoReturn:
    _require_json(args, "doctor")
    _emit_json(
        artifact_facade.artifact_doctor(_index_path(args), ArtifactDoctorOptionsWire())
    )


def _node_upsert_from_args(args: argparse.Namespace) -> ArtifactNodeUpsertWire:
    if not args.artifact_id:
        raise ValueError("node upsert requires -a/--artifact-id")
    if not args.kind:
        raise ValueError("node upsert requires -k/--kind")
    metadata = _json_object(args.metadata_json, "metadata JSON")
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


def _payload_from_args(args: argparse.Namespace) -> ArtifactPayloadWire:
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
        payload=_json_value(args.payload_json, "payload JSON"),
    )


def _links_from_args(args: argparse.Namespace) -> list[ArtifactLinkUpsertWire]:
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
    data = _json_object(raw, "link JSON")
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


def _json_value(raw: str, label: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed {label}: {exc.msg}") from exc


def _json_object(raw: str | None, label: str) -> dict[str, object]:
    if raw is None:
        return {}
    value = _json_value(raw, label)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _merge_mutation_results(
    operation: str,
    results: list[ArtifactMutationResultWire],
) -> ArtifactMutationResultWire:
    return ArtifactMutationResultWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        operation=operation,
        nodes_added=sum(result.nodes_added for result in results),
        nodes_updated=sum(result.nodes_updated for result in results),
        nodes_removed=sum(result.nodes_removed for result in results),
        links_added=sum(result.links_added for result in results),
        links_updated=sum(result.links_updated for result in results),
        links_removed=sum(result.links_removed for result in results),
        tombstones_added=sum(result.tombstones_added for result in results),
        affected_node_ids=_unique(
            node_id for result in results for node_id in result.affected_node_ids
        ),
        affected_link_ids=_unique(
            link_id for result in results for link_id in result.affected_link_ids
        ),
        tombstone_ids=_unique(
            tombstone_id for result in results for tombstone_id in result.tombstone_ids
        ),
        errors=[error for result in results for error in result.errors],
    )


def _unique(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        unique_values.append(text)
    return unique_values
