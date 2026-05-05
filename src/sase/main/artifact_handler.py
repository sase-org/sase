"""Handler for ``sase artifact`` subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

from sase.core import artifact_facade
from sase.core.artifact_wire import (
    ARTIFACT_ROOT_ID,
    ArtifactDoctorOptionsWire,
    ArtifactGraphOptionsWire,
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
            _not_implemented("sase artifact add is not implemented yet")
        if sub == "remove":
            _not_implemented("sase artifact remove is not implemented yet")
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


def _require_json(args: argparse.Namespace, command: str) -> None:
    if not getattr(args, "json", False):
        raise ValueError(
            f"human output is not implemented yet; use `sase artifact {command} -j`"
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


def _not_implemented(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(1)
