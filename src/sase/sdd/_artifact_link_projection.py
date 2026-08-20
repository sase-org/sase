"""Build artifact-link rows and their managed Markdown projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sase.agents_sync.referenced_by_outbox_models import ReferencedByOutboxItem
from sase.core.rust import require_rust_binding
from sase.sdd._referenced_by_refresh_utils import relative_path
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from sase.sdd.hosted_links import resolve_hosted_branch

if TYPE_CHECKING:
    from sase.sdd.store import SddStore

_CURATED_ORIGINS = frozenset({"manual", "migrated"})
_AUTOMATIC_ORIGINS = frozenset({"prompt_ref", "read"})
_MAX_RENDERED_ROWS = 50


def artifact_projection_document(asset: Path) -> Path:
    """Return the Markdown document that projects links for *asset*."""

    suffix = asset.suffix.casefold()
    if suffix in {".md", ".markdown"}:
        return asset
    companion = require_rust_binding("companion_md_path")(str(asset))
    return Path(str(companion["path"])).expanduser().resolve(strict=False)


def companion_seed(asset: Path, document: Path) -> str:
    """Create the initial body for a generated companion document."""

    if document == asset:
        return ""
    rel_asset = relative_path(document.parent, asset)
    title = asset.name.replace("\n", " ")
    suffix = asset.suffix.casefold()
    if suffix in {".apng", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}:
        preview = f"![{title}](./{rel_asset})"
        kind = "image"
    else:
        preview = f"[{title}](./{rel_asset})"
        kind = "artifact"
    return (
        f"# {title}\n\n"
        f"{preview}\n\n"
        f"_Typed links for this {kind}. This file is generated; do not hand-edit._\n"
    )


def artifact_link_row(item: ReferencedByOutboxItem) -> dict[str, object]:
    """Translate one outbox request into a v2 artifact-link row."""

    target_ref = item.canonical_ref or item.artifact_id
    description = item.description.strip() or f"{item.origin} reference to {target_ref}"
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": f"agent:{item.global_agent}",
        "relation": item.relation,
        "target_ref": target_ref,
        "description": description[:240],
        "origin": item.origin,
        "created_by": item.global_agent,
        "created_at": _item_created_at(item),
        "uses": item.uses,
    }


def _item_created_at(item: ReferencedByOutboxItem) -> str:
    timestamp = item.created_at or item.updated_at
    if timestamp > 0:
        return (
            datetime.fromtimestamp(timestamp, tz=UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    return f"{item.published_date}T00:00:00Z"


def preview_link_rows(
    existing_rows: Sequence[Mapping[str, Any]],
    incoming_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Apply incoming rows in memory without changing the link store."""

    rows = [dict(row) for row in existing_rows]
    upsert = require_rust_binding("artifact_link_upsert_row")
    for incoming in incoming_rows:
        outcome = upsert(rows, dict(incoming))
        rows = [dict(row) for row in outcome["rows"]]
    return tuple(rows)


def link_rows_changed(
    existing_rows: Sequence[Mapping[str, Any]],
    preview_rows: Sequence[Mapping[str, Any]],
) -> bool:
    """Return whether the projected link-store rows differ."""

    return [dict(row) for row in existing_rows] != [dict(row) for row in preview_rows]


def render_artifact_link_projection(
    current: str,
    *,
    artifact_id: str,
    rows: Sequence[Mapping[str, Any]],
    store: SddStore,
    resolver: Any,
    companion: bool = False,
) -> str:
    """Render curated and automatic link rows into managed blocks."""

    links_rows = _table_rows_for_origins(
        artifact_id,
        rows,
        origins=_CURATED_ORIGINS,
        store=store,
        resolver=resolver,
        include_uses=False,
    )
    automatic_rows = _table_rows_for_origins(
        artifact_id,
        rows,
        origins=_AUTOMATIC_ORIGINS,
        store=store,
        resolver=resolver,
        include_uses=True,
    )
    links_table = _links_table(links_rows, automatic_count=len(automatic_rows))
    if companion:
        return _render_companion_projection(
            current,
            links_table=links_table,
            referenced_by_table=_referenced_by_table(automatic_rows),
        )
    updated = str(require_rust_binding("links_block_upsert")(current, links_table))
    referenced_by_table = _referenced_by_table(automatic_rows)
    return str(
        require_rust_binding("referenced_by_block_upsert")(
            updated,
            referenced_by_table,
        )
    )


def _render_companion_projection(
    current: str,
    *,
    links_table: Mapping[str, object],
    referenced_by_table: Mapping[str, object],
) -> str:
    body = _strip_managed_link_blocks(current).rstrip()
    blocks: list[str] = []
    if links_table.get("rows"):
        blocks.append(
            _managed_block(
                "links", str(require_rust_binding("links_block_render")(links_table))
            )
        )
    if referenced_by_table.get("rows"):
        blocks.append(
            _managed_block(
                "referenced-by",
                str(
                    require_rust_binding("referenced_by_block_render")(
                        referenced_by_table
                    )
                ),
            )
        )
    if not blocks:
        return f"{body}\n" if body else ""
    return f"{body}\n\n" + "\n\n".join(blocks) + "\n"


def _managed_block(name: str, body: str) -> str:
    return f"<!-- sase:{name}:start -->\n\n{body}\n\n<!-- sase:{name}:end -->"


def _table_rows_for_origins(
    artifact_id: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    origins: frozenset[str],
    store: SddStore,
    resolver: Any,
    include_uses: bool,
) -> tuple[dict[str, object], ...]:
    rendered: list[dict[str, object]] = []
    for row in rows:
        if str(row.get("origin") or "") not in origins:
            continue
        projected = _project_row(
            artifact_id,
            row,
            store=store,
            resolver=resolver,
            include_uses=include_uses,
        )
        if projected is not None:
            rendered.append(projected)
    rendered.sort(
        key=lambda item: (
            str(cast(Mapping[str, object], item["values"]).get("relation") or ""),
            str(cast(Mapping[str, object], item["values"]).get("artifact") or ""),
        )
    )
    return tuple(rendered)


def _project_row(
    artifact_id: str,
    row: Mapping[str, Any],
    *,
    store: SddStore,
    resolver: Any,
    include_uses: bool,
) -> dict[str, object] | None:
    source = str(row.get("source_ref") or "")
    target = str(row.get("target_ref") or "")
    if artifact_id == source:
        other = target
        this_is_source = True
    elif artifact_id == target:
        other = source
        this_is_source = False
    else:
        return None
    relation = str(
        require_rust_binding("artifact_relation_label")(
            str(row.get("relation") or ""),
            this_is_source,
        )
    )
    values = {
        "relation": relation,
        "artifact": other,
        "why": str(row.get("description") or ""),
    }
    if include_uses:
        values["uses"] = str(row.get("uses") or "0")
    link_targets: dict[str, str] = {}
    url = _artifact_url(other, store=store, resolver=resolver)
    if url:
        link_targets["artifact"] = url
    return {"values": values, "link_targets": link_targets}


def _links_table(
    rows: Sequence[Mapping[str, object]],
    *,
    automatic_count: int,
) -> dict[str, object]:
    table_rows, omitted = _cap_rows(rows)
    table: dict[str, object] = {
        "schema_version": int(
            require_rust_binding("referenced_by_wire_schema_version")()
        ),
        "columns": [
            {"key": "relation", "label": "Relation", "numeric": False},
            {"key": "artifact", "label": "Artifact", "numeric": False},
            {"key": "why", "label": "Why", "numeric": False},
        ],
        "rows": table_rows,
        "omitted": omitted,
    }
    if table_rows and automatic_count > 0:
        table["pointer"] = (
            f"Plus {automatic_count} automatic references — see "
            "[Referenced By](#referenced-by)."
        )
    return table


def _referenced_by_table(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    table_rows, omitted = _cap_rows(rows)
    return {
        "schema_version": int(
            require_rust_binding("referenced_by_wire_schema_version")()
        ),
        "columns": [
            {"key": "relation", "label": "Relation", "numeric": False},
            {"key": "artifact", "label": "Artifact", "numeric": False},
            {"key": "why", "label": "Why", "numeric": False},
            {"key": "uses", "label": "Uses", "numeric": True},
        ],
        "rows": table_rows,
        "omitted": omitted,
    }


def _cap_rows(
    rows: Sequence[Mapping[str, object]],
) -> tuple[tuple[Mapping[str, object], ...], int]:
    kept = tuple(rows[:_MAX_RENDERED_ROWS])
    return kept, max(0, len(rows) - len(kept))


def _artifact_url(artifact_ref: str, *, store: SddStore, resolver: Any) -> str | None:
    kind, separator, value = artifact_ref.partition(":")
    if not separator:
        return None
    if kind == "agent":
        return resolver.agent_url(value)
    if kind == "bead":
        return resolver.bead_url(value)
    if kind == "commit":
        return resolver.commit_url(value)
    if kind == "plan":
        return resolver.plan_url(artifact_ref)
    if kind == "stitch":
        return resolver.commit_url(value)
    return _document_url(kind, value, store=store, resolver=resolver)


def _document_url(
    kind: str,
    repo_relpath: str,
    *,
    store: SddStore,
    resolver: Any,
) -> str | None:
    try:
        repo_root = store.repo_root_for_kind(kind).expanduser().resolve(strict=False)
    except Exception:
        return None
    branch = resolve_hosted_branch(repo_root)
    if branch is None:
        return None
    try:
        return resolver.blob_url_for_repository(repo_root, branch, repo_relpath)
    except Exception:
        return None


def _strip_managed_link_blocks(text: str) -> str:
    """Remove both managed link projection blocks from *text*."""

    without_links = str(require_rust_binding("links_block_remove")(text))
    return str(require_rust_binding("referenced_by_block_remove")(without_links))


def safety_body(text: str) -> str:
    """Normalize unmanaged text for a managed-block safety comparison."""

    stripped = _strip_managed_link_blocks(text)
    while "\n\n\n" in stripped:
        stripped = stripped.replace("\n\n\n", "\n\n")
    return stripped
