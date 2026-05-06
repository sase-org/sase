"""Subcommand implementations for the ``sase artifact`` CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn, Protocol

from sase.core.artifact_wire import (
    ARTIFACT_ROOT_ID,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDoctorOptionsWire,
    ArtifactDoctorWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactLinkRemoveWire,
    ArtifactLinkUpsertWire,
    ArtifactMutationResultWire,
    ArtifactNodeRemoveWire,
    ArtifactNodeUpsertWire,
    ArtifactPayloadWire,
    ArtifactQueryWire,
    ArtifactRebuildRequestWire,
)

from .builders import (
    links_from_args,
    node_upsert_from_args,
    payload_from_args,
    query_from_args,
)
from .common import (
    emit_json,
    emit_json_with_exit,
    emit_mutation_result,
    index_path,
    merge_mutation_results,
)
from .formatters import (
    doctor_ok,
    format_detail,
    format_doctor,
    format_graph_text,
    format_node_table,
)


class _ArtifactFacade(Protocol):
    def artifact_add(
        self,
        index_path: Path,
        request: ArtifactNodeUpsertWire | ArtifactPayloadWire | ArtifactLinkUpsertWire,
    ) -> ArtifactMutationResultWire: ...

    def artifact_remove(
        self,
        index_path: Path,
        request: ArtifactNodeRemoveWire | ArtifactLinkRemoveWire,
    ) -> ArtifactMutationResultWire: ...

    def artifact_list(self, index_path: Path, query: ArtifactQueryWire) -> object: ...

    def artifact_search(self, index_path: Path, query: ArtifactQueryWire) -> object: ...

    def artifact_show(self, index_path: Path, artifact_id: str) -> object: ...

    def artifact_graph(
        self, index_path: Path, options: ArtifactGraphOptionsWire
    ) -> ArtifactGraphWire: ...

    def artifact_export(
        self, index_path: Path, options: ArtifactGraphOptionsWire, output_format: str
    ) -> str: ...

    def artifact_rebuild_request(
        self,
        *,
        projects_root: Path | str | None = None,
        workspace_root: Path | str | None = None,
        beads_dir: Path | str | None = None,
        include_sources: tuple[str, ...] = (),
        exclude_sources: tuple[str, ...] = (),
        target_path: Path | str | None = None,
        artifact_dir: Path | str | None = None,
        stale_cleanup: str = "none",
    ) -> ArtifactRebuildRequestWire: ...

    def artifact_rebuild(
        self, index_path: Path, request: ArtifactRebuildRequestWire | None = None
    ) -> ArtifactMutationResultWire: ...

    def artifact_doctor(
        self, index_path: Path, options: ArtifactDoctorOptionsWire
    ) -> ArtifactDoctorWire: ...


def handle_artifact_command(
    args: argparse.Namespace, artifact_facade: _ArtifactFacade
) -> NoReturn:
    """Dispatch to the appropriate artifact sub-handler."""
    sub = getattr(args, "artifact_subcommand", None)

    try:
        if sub == "add":
            _handle_add(args, artifact_facade)
        elif sub == "remove":
            _handle_remove(args, artifact_facade)
        elif sub == "list":
            _handle_list(args, artifact_facade)
        elif sub == "search":
            _handle_search(args, artifact_facade)
        elif sub == "show":
            _handle_show(args, artifact_facade)
        elif sub == "graph":
            _handle_graph(args, artifact_facade)
        elif sub in {"rebuild", "sync"}:
            _handle_rebuild(args, artifact_facade)
        elif sub == "doctor":
            _handle_doctor(args, artifact_facade)
    except Exception as exc:
        print(f"sase artifact {sub or ''}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(
        "Usage: sase artifact {add,remove,list,search,show,graph,rebuild,sync,doctor}"
    )
    sys.exit(1)


def _handle_add(args: argparse.Namespace, artifact_facade: _ArtifactFacade) -> NoReturn:
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
        requests.append(node_upsert_from_args(args))
    if args.payload_json is not None or args.payload_type:
        requests.append(payload_from_args(args))
    requests.extend(links_from_args(args))

    if not requests:
        raise ValueError(
            "add requires a node (-a/-k), payload (-a/-P/-p), or link (-l/-L)"
        )

    results = [
        artifact_facade.artifact_add(index_path(args), request) for request in requests
    ]
    emit_mutation_result(merge_mutation_results("add", results), json_output=args.json)


def _handle_remove(
    args: argparse.Namespace, artifact_facade: _ArtifactFacade
) -> NoReturn:
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
        artifact_facade.artifact_remove(index_path(args), request)
        for request in requests
    ]
    emit_mutation_result(
        merge_mutation_results("remove", results),
        json_output=args.json,
    )


def _handle_list(
    args: argparse.Namespace, artifact_facade: _ArtifactFacade
) -> NoReturn:
    result = artifact_facade.artifact_list(index_path(args), query_from_args(args))
    if args.json:
        emit_json(result)
    print(format_node_table(result))
    sys.exit(0)


def _handle_search(
    args: argparse.Namespace, artifact_facade: _ArtifactFacade
) -> NoReturn:
    result = artifact_facade.artifact_search(index_path(args), query_from_args(args))
    if args.json:
        emit_json(result)
    print(format_node_table(result))
    sys.exit(0)


def _handle_show(
    args: argparse.Namespace, artifact_facade: _ArtifactFacade
) -> NoReturn:
    result = artifact_facade.artifact_show(index_path(args), args.artifact_id)
    if args.json:
        emit_json(result)
    print(format_detail(result, artifact_id=args.artifact_id))
    sys.exit(0)


def _handle_graph(
    args: argparse.Namespace, artifact_facade: _ArtifactFacade
) -> NoReturn:
    output_format = "json" if args.json else args.format
    options = ArtifactGraphOptionsWire(
        root_id=args.artifact_id if args.artifact_id else ARTIFACT_ROOT_ID,
        max_depth=args.depth,
        link_types=tuple(args.link_type),
        include_inbound=args.include_inbound,
        include_outbound=args.include_outbound,
        full_graph=args.full,
        limit=args.limit,
    )
    if output_format == "json":
        emit_json(artifact_facade.artifact_graph(index_path(args), options))
    if output_format == "text":
        print(
            format_graph_text(artifact_facade.artifact_graph(index_path(args), options))
        )
        sys.exit(0)
    if output_format in {"dot", "mermaid"}:
        print(
            artifact_facade.artifact_export(
                index_path(args),
                options,
                output_format,
            ),
            end="",
        )
        sys.exit(0)
    raise ValueError(f"unsupported graph output format: {output_format}")


def _handle_rebuild(
    args: argparse.Namespace, artifact_facade: _ArtifactFacade
) -> NoReturn:
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
    result = artifact_facade.artifact_rebuild(index_path(args), request)
    emit_mutation_result(result, json_output=args.json)


def _handle_doctor(
    args: argparse.Namespace, artifact_facade: _ArtifactFacade
) -> NoReturn:
    result = artifact_facade.artifact_doctor(
        index_path(args), ArtifactDoctorOptionsWire()
    )
    exit_code = 0 if doctor_ok(result) else 1
    if args.json:
        emit_json_with_exit(result, exit_code=exit_code)
    print(format_doctor(result))
    sys.exit(exit_code)
