"""Consume transient plan ``links:`` frontmatter into typed artifact links."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any, cast

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_projection import preview_link_rows
from sase.sdd._artifact_link_refresh import preview_artifact_link_projection_file
from sase.sdd._artifact_link_store_support import (
    kind_of_ref,
    validate_artifact_link_row,
)
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
    assembled_artifact_relations,
    canonicalize_artifact_link_ref,
    resolve_artifact_link_store,
)
from sase.sdd.frontmatter import remove_frontmatter_fields


_INLET_KINDS = frozenset({"absent", "entries", "unrecognized"})
_PLACEHOLDER_SOURCE_REF = "plan:202608/__frontmatter_link_inlet__.md"
_MANUAL_ORIGIN = "manual"


class ArtifactLinkFrontmatterInletError(ValueError):
    """Raised when authored ``links:`` frontmatter cannot be consumed."""


@dataclass(frozen=True, slots=True)
class _ArtifactLinkFrontmatterInletEntry:
    """One authored ``links:`` frontmatter row."""

    target_ref: str
    relation: str
    description: str


@dataclass(frozen=True, slots=True)
class _ArtifactLinkFrontmatterInlet:
    """Parsed plan-link inlet plus the document with the inlet removed."""

    kind: str
    entries: tuple[_ArtifactLinkFrontmatterInletEntry, ...]
    content_without_inlet: str


def parse_plan_artifact_link_inlet(content: str) -> _ArtifactLinkFrontmatterInlet:
    """Parse one plan document's transient ``links:`` frontmatter inlet."""

    payload = cast(
        dict[str, Any],
        require_rust_binding("artifact_link_frontmatter_inlet")(content),
    )
    kind = str(payload.get("kind") or "")
    if kind not in _INLET_KINDS:
        raise RuntimeError(f"sase_core_rs returned unknown links inlet kind: {kind}")
    raw_entries = payload.get("entries")
    if raw_entries is None:
        raw_entries = []
    if not isinstance(raw_entries, list):
        raise RuntimeError("sase_core_rs returned malformed links inlet entries")
    entries: list[_ArtifactLinkFrontmatterInletEntry] = []
    for index, item in enumerate(raw_entries):
        if not isinstance(item, dict):
            raise RuntimeError("sase_core_rs returned malformed links inlet entry")
        entries.append(_entry_from_payload(cast(dict[str, Any], item), index))
    content_without_inlet = (
        remove_frontmatter_fields(content, ("links",)) if kind == "entries" else content
    )
    return _ArtifactLinkFrontmatterInlet(
        kind=kind,
        entries=tuple(entries),
        content_without_inlet=content_without_inlet,
    )


def validate_plan_artifact_link_inlet(
    inlet: _ArtifactLinkFrontmatterInlet,
) -> None:
    """Validate a parsed inlet before plan proposal mutates the source file."""

    if inlet.kind == "absent":
        return
    if inlet.kind == "unrecognized":
        raise ArtifactLinkFrontmatterInletError(
            "frontmatter field `links` must be a list of mappings with string "
            "`ref`, `relation`, and `description` keys"
        )
    for index, entry in enumerate(inlet.entries):
        _row_for_entry(
            entry,
            index=index,
            source_ref=_PLACEHOLDER_SOURCE_REF,
            created_by="validation",
            created_at="1970-01-01T00:00:00Z",
        )


def publish_plan_artifact_link_inlet(
    document_path: Path,
    *,
    source_ref: str,
    inlet: _ArtifactLinkFrontmatterInlet,
    store: ArtifactLinkStore | None = None,
) -> tuple[dict[str, Any], ...]:
    """Persist inlet rows and refresh the archived plan's managed links block."""

    if not inlet.entries:
        return ()

    source_ref = canonicalize_artifact_link_ref(source_ref)
    link_store = store or resolve_artifact_link_store()
    if link_store.sdd_store is None:
        raise ArtifactLinkFrontmatterInletError(
            "artifact-link frontmatter ingestion requires an SDD store"
        )

    rows = tuple(
        _row_for_entry(
            entry,
            index=index,
            source_ref=source_ref,
            created_by=_created_by(),
            created_at=_created_at(),
        )
        for index, entry in enumerate(inlet.entries)
    )
    existing_rows = link_store.load_artifact_rows(source_ref)
    projected_rows = preview_link_rows(existing_rows, rows)
    document, current, updated = preview_artifact_link_projection_file(
        document_path,
        artifact_id=source_ref,
        rows=projected_rows,
        store=link_store.sdd_store,
    )

    changed_indexes: list[Path] = []
    beads_changed = False
    for row in rows:
        outcome = link_store.upsert_row(row)
        changed_indexes.extend(
            Path(path) for path in outcome.get("changed_indexes") or ()
        )
        beads_changed = beads_changed or bool(outcome.get("beads_changed"))
    _persist_link_mutation(
        link_store,
        changed_indexes=tuple(dict.fromkeys(changed_indexes)),
        beads_changed=beads_changed,
    )
    if updated != current:
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text(updated, encoding="utf-8")
    return rows


def _entry_from_payload(
    payload: dict[str, Any], index: int
) -> _ArtifactLinkFrontmatterInletEntry:
    try:
        artifact_ref = _required_text(payload, "ref")
        relation = _required_text(payload, "relation")
        description = _required_text(payload, "description")
    except TypeError as exc:
        raise RuntimeError(f"malformed links[{index}] inlet payload") from exc
    return _ArtifactLinkFrontmatterInletEntry(
        target_ref=artifact_ref,
        relation=relation,
        description=description,
    )


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise TypeError(key)
    return value


def _row_for_entry(
    entry: _ArtifactLinkFrontmatterInletEntry,
    *,
    index: int,
    source_ref: str,
    created_by: str,
    created_at: str,
) -> dict[str, Any]:
    try:
        source = canonicalize_artifact_link_ref(source_ref)
        target = canonicalize_artifact_link_ref(entry.target_ref)
        relation = _cli_writable_relation(entry.relation, index=index)
        _validate_direction(
            relation,
            source_kind=kind_of_ref(source),
            target_kind=kind_of_ref(target),
            index=index,
        )
        return validate_artifact_link_row(
            {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "source_ref": source,
                "relation": relation["slug"],
                "target_ref": target,
                "description": entry.description,
                "origin": _MANUAL_ORIGIN,
                "created_by": created_by,
                "created_at": created_at,
                "uses": 1,
            }
        )
    except ArtifactLinkFrontmatterInletError:
        raise
    except (RuntimeError, TypeError, ValueError) as exc:
        raise ArtifactLinkFrontmatterInletError(
            f"invalid links[{index}]: {exc}"
        ) from exc


def _cli_writable_relation(slug: str, *, index: int) -> dict[str, Any]:
    try:
        relation = dict(require_rust_binding("artifact_relation_lookup")(slug))
    except (RuntimeError, TypeError, ValueError) as exc:
        raise ArtifactLinkFrontmatterInletError(
            f"invalid links[{index}].relation: {exc}"
        ) from exc

    written_by = str(relation.get("written_by") or "")
    if written_by == "cli":
        return relation
    cli_slugs = ", ".join(
        str(item.get("slug") or "")
        for item in assembled_artifact_relations()
        if str(item.get("written_by") or "") == "cli"
    )
    name = str(relation.get("slug") or slug)
    raise ArtifactLinkFrontmatterInletError(
        f"invalid links[{index}].relation: relation `{name}` is not writable "
        f"from plan links frontmatter; expected one of {cli_slugs}"
    )


def _validate_direction(
    relation: dict[str, Any],
    *,
    source_kind: str,
    target_kind: str,
    index: int,
) -> None:
    _validate_recommended_kind(
        relation,
        endpoint="source",
        actual=source_kind,
        index=index,
    )
    _validate_recommended_kind(
        relation,
        endpoint="target",
        actual=target_kind,
        index=index,
    )


def _validate_recommended_kind(
    relation: dict[str, Any],
    *,
    endpoint: str,
    actual: str,
    index: int,
) -> None:
    raw_expected = relation.get(f"recommended_{endpoint}_kinds") or ()
    expected = tuple(str(item) for item in raw_expected)
    if not expected or actual in expected:
        return
    name = str(relation.get("slug") or "")
    example = str(relation.get("positive_example") or "")
    expected_text = " or ".join(expected)
    raise ArtifactLinkFrontmatterInletError(
        f"invalid links[{index}].ref: relation `{name}` expects {endpoint} "
        f"artifact kind {expected_text}; got {actual}. Example: {example}"
    )


def _persist_link_mutation(
    store: ArtifactLinkStore,
    *,
    changed_indexes: tuple[Path, ...],
    beads_changed: bool,
) -> None:
    from sase.sdd._artifact_link_commit import (
        ArtifactLinkPersistError,
        persist_artifact_link_graph_mutation,
    )

    try:
        persist_artifact_link_graph_mutation(
            store,
            changed_indexes=changed_indexes,
            beads_changed=beads_changed,
        )
    except ArtifactLinkPersistError as exc:
        raise ArtifactLinkFrontmatterInletError(exc.diagnostic) from exc


def _created_by() -> str:
    from sase.agent.identity import discover_agent_identity

    identity = discover_agent_identity()
    if identity is not None:
        return identity.name
    return os.environ.get("USER") or "unknown"


def _created_at() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "ArtifactLinkFrontmatterInletError",
    "parse_plan_artifact_link_inlet",
    "publish_plan_artifact_link_inlet",
    "validate_plan_artifact_link_inlet",
]
