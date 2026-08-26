"""``sase artifact link add``, ``list``, and ``rm`` against the store adapter."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import UTC, datetime
import json
import os
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.agent.identity import discover_agent_identity
from sase.core.rust import require_rust_binding
from sase.core.time import format_local
from sase.sdd._artifact_link_store_support import unique_rows
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
    assembled_artifact_relations,
    canonicalize_artifact_link_ref,
    resolve_artifact_link_store,
)


_CLI_ORIGIN = "manual"


def handle_link_add(args: argparse.Namespace) -> int:
    """Add or rewrite one typed artifact link."""

    try:
        outcome = add_artifact_link(
            source_ref=args.source_ref,
            relation=args.relation,
            target_ref=args.target_ref,
            why=args.why,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    kind = str(outcome.get("kind") or "unchanged")
    stored = dict(outcome.get("row") or {})
    _print_add_outcome(kind, stored)
    return 0


def add_artifact_link(
    *,
    source_ref: str,
    relation: str,
    target_ref: str,
    why: str,
) -> dict[str, Any]:
    """Add or rewrite one manual typed artifact link and persist the mutation."""

    source = str(source_ref).strip()
    target = str(target_ref).strip()
    description = _validated_why(why)
    if not source:
        raise ValueError("source artifact reference is required")
    if not target:
        raise ValueError("target artifact reference is required")
    relation = _cli_writable_relation(relation)
    store = _store()
    identity = _created_by()
    row = {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": source,
        "relation": relation,
        "target_ref": target,
        "description": description,
        "origin": _CLI_ORIGIN,
        "created_by": identity,
        "created_at": _created_at(),
        "uses": 1,
    }
    outcome = store.upsert_row(row)
    _persist_link_mutation(
        store,
        changed_indexes=tuple(outcome.get("changed_indexes") or ()),
        beads_changed=bool(outcome.get("beads_changed")),
    )
    return dict(outcome)


def _validated_why(value: str) -> str:
    why = " ".join(str(value).strip().splitlines())
    if not why:
        raise ValueError("artifact link reason is required")
    if len(why) > 240:
        raise ValueError("artifact link reason must be 240 characters or fewer")
    return why


def handle_link_list(args: argparse.Namespace) -> int:
    """List recent project links or one artifact's neighborhood."""

    try:
        store = _store()
        reference = getattr(args, "reference", None)
        canonical = (
            None if not reference else canonicalize_artifact_link_ref(str(reference))
        )
        rows = (
            list(store.load_artifact_rows(canonical))
            if canonical is not None
            else unique_rows(
                [*store.load_aggregate().get("rows", []), *store.projected_rows()]
            )
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    rows = _filter_rows(
        rows,
        reference=canonical,
        direction=str(getattr(args, "direction", "both") or "both"),
        origin=getattr(args, "origin", None),
        relation=getattr(args, "relation", None),
    )
    rows.sort(key=_sort_key, reverse=True)
    limit = getattr(args, "limit", 50)
    if isinstance(limit, int) and limit > 0:
        rows = rows[:limit]

    if bool(getattr(args, "json", False)):
        json.dump(rows, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    _print_link_table(rows, reference=canonical)
    return 0


def handle_link_rm(args: argparse.Namespace) -> int:
    """Remove stored edges between two artifacts."""

    try:
        relation = getattr(args, "relation", None)
        if relation:
            relation = str(
                require_rust_binding("artifact_relation_lookup")(str(relation))["slug"]
            )
        store = _store()
        removed = store.remove_rows(
            args.source_ref,
            args.target_ref,
            relation=None if not relation else str(relation),
        )
        _persist_link_mutation(
            store,
            changed_indexes=removed.changed_indexes,
            beads_changed=removed.beads_changed,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not removed:
        print("removed 0 links")
        return 0
    for row in removed:
        print(
            "removed "
            f"{row.get('relation')} {row.get('source_ref')} -> {row.get('target_ref')}"
        )
    return 0


def _store() -> ArtifactLinkStore:
    return resolve_artifact_link_store()


def _persist_link_mutation(
    store: ArtifactLinkStore,
    *,
    changed_indexes: tuple[Any, ...],
    beads_changed: bool,
) -> None:
    from pathlib import Path

    from sase.sdd._artifact_link_commit import (
        ArtifactLinkPersistError,
        persist_artifact_link_graph_mutation,
    )

    try:
        persist_artifact_link_graph_mutation(
            store,
            changed_indexes=tuple(Path(path) for path in changed_indexes),
            beads_changed=beads_changed,
        )
    except ArtifactLinkPersistError as exc:
        raise RuntimeError(exc.diagnostic) from exc


def _cli_writable_relation(slug: str) -> str:
    looked_up = dict(require_rust_binding("artifact_relation_lookup")(slug))
    name = str(looked_up.get("slug") or slug)
    written_by = str(looked_up.get("written_by") or "")
    if written_by == "cli":
        return name
    cli_slugs = ", ".join(
        str(item.get("slug") or "")
        for item in assembled_artifact_relations()
        if str(item.get("written_by") or "") == "cli"
    )
    if name == "read":
        raise ValueError(
            "relation `read` is written by `sase artifact read`, not "
            f"`sase artifact link add`; expected one of {cli_slugs}"
        )
    if name == "cites":
        raise ValueError(
            "relation `cites` is written by prompt-ref expansion, not "
            f"`sase artifact link add`; expected one of {cli_slugs}"
        )
    raise ValueError(
        f"relation `{name}` is not writable by sase artifact link add; "
        f"expected one of {cli_slugs}"
    )


def _created_by() -> str:
    identity = discover_agent_identity()
    if identity is not None:
        return identity.name
    return os.environ.get("USER") or "unknown"


def _created_at() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _filter_rows(
    rows: list[dict[str, Any]],
    *,
    reference: str | None,
    direction: str,
    origin: str | None,
    relation: str | None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    origin_filter = None if origin is None else str(origin).strip()
    relation_filter = None if relation is None else str(relation).strip()
    for row in rows:
        if origin_filter and str(row.get("origin") or "") != origin_filter:
            continue
        if relation_filter and str(row.get("relation") or "") != relation_filter:
            continue
        if reference is None or _direction_matches(row, reference, direction):
            filtered.append(row)
    return filtered


def _direction_matches(row: Mapping[str, Any], reference: str, direction: str) -> bool:
    source = str(row.get("source_ref") or "")
    target = str(row.get("target_ref") or "")
    if direction == "out":
        return source == reference
    if direction == "in":
        return target == reference
    return reference in {source, target}


def _sort_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("created_at") or ""),
        str(row.get("relation") or ""),
        str(row.get("source_ref") or ""),
        str(row.get("target_ref") or ""),
    )


def _print_add_outcome(kind: str, row: dict[str, Any]) -> None:
    console = Console()
    style = {"added": "green", "updated": "yellow", "unchanged": "cyan"}.get(
        kind, "white"
    )
    console.print(
        f"[{style}]{kind}[/{style}] {row.get('relation')} "
        f"{row.get('source_ref')} -> {row.get('target_ref')}"
    )
    description = str(row.get("description") or "")
    if description:
        console.print(f"  {description}")


def _print_link_table(rows: list[dict[str, Any]], *, reference: str | None) -> None:
    console = Console()
    title = (
        f"Links for {reference} ({len(rows)})"
        if reference
        else f"Artifact links ({len(rows)})"
    )
    if not rows:
        console.print(
            Panel(
                "[dim]No artifact links found.[/dim]",
                title=title,
                border_style="cyan",
            )
        )
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("RELATION", no_wrap=True)
    table.add_column("SOURCE", style="bold")
    table.add_column("TARGET", style="bold")
    table.add_column("ORIGIN", no_wrap=True)
    table.add_column("WHY")
    table.add_column("CREATED", no_wrap=True)
    for row in rows:
        raw_created = row.get("created_at")
        created = format_local(
            raw_created if isinstance(raw_created, str) else None,
            "%Y-%m-%d %H:%M",
            default="-",
        )
        table.add_row(
            str(row.get("relation") or "-"),
            str(row.get("source_ref") or "-"),
            str(row.get("target_ref") or "-"),
            str(row.get("origin") or "-"),
            str(row.get("description") or "-"),
            created,
        )
    console.print(Panel(table, title=title, border_style="cyan"))


__all__ = ["handle_link_add", "handle_link_list", "handle_link_rm"]
