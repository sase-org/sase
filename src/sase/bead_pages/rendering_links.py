"""Managed Links / Referenced By tables on generated bead pages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.bead.model import Issue
from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_beads import rows_touching_bead

_CURATED_ORIGINS = frozenset({"manual", "migrated"})
_AUTOMATIC_ORIGINS = frozenset({"prompt_ref", "read"})
_LINKS_SCHEMA_VERSION = 1
_LINKS_COLUMNS = (
    {"key": "relation", "label": "Relation", "numeric": False},
    {"key": "artifact", "label": "Artifact", "numeric": False},
    {"key": "why", "label": "Why", "numeric": False},
)
_REFERENCED_BY_COLUMNS = (
    {"key": "relation", "label": "Relation", "numeric": False},
    {"key": "artifact", "label": "Artifact", "numeric": False},
    {"key": "why", "label": "Why", "numeric": False},
    {"key": "uses", "label": "Uses", "numeric": True},
)


def apply_bead_page_link_tables(
    document: str,
    issue: Issue,
    all_issues: Sequence[Issue],
    *,
    extra_rows: Sequence[Mapping[str, Any]] = (),
    link_urls: Mapping[str, str] | None = None,
    identity_line_count: int,
) -> str:
    """Write the managed link tables from event/store truth, never from Markdown."""

    stripped = str(require_rust_binding("links_block_remove")(document))
    stripped = str(require_rust_binding("referenced_by_block_remove")(stripped))
    if not stripped.endswith("\n"):
        stripped += "\n"

    rows = rows_touching_bead(all_issues, issue.id, extra_rows=extra_rows)
    curated = [row for row in rows if str(row.get("origin") or "") in _CURATED_ORIGINS]
    automatic = [
        row for row in rows if str(row.get("origin") or "") in _AUTOMATIC_ORIGINS
    ]
    urls = dict(link_urls or {})
    prefix, rest = _split_identity(stripped, identity_line_count)
    with_links = _insert_links_block(
        prefix,
        rest,
        issue_id=issue.id,
        rows=curated,
        automatic_count=len(automatic),
        urls=urls,
    )
    return str(
        require_rust_binding("referenced_by_block_upsert")(
            with_links,
            _referenced_by_table(issue.id, automatic, urls),
        )
    )


def _split_identity(document: str, identity_line_count: int) -> tuple[str, str]:
    lines = document.splitlines()
    prefix = "\n".join(lines[:identity_line_count]).rstrip()
    rest = "\n".join(lines[identity_line_count:]).strip("\n")
    return prefix, rest


def _insert_links_block(
    prefix: str,
    rest: str,
    *,
    issue_id: str,
    rows: Sequence[Mapping[str, Any]],
    automatic_count: int,
    urls: Mapping[str, str],
) -> str:
    table = _links_table(issue_id, rows, automatic_count, urls)
    if not table["rows"]:
        if rest:
            return f"{prefix}\n\n{rest}\n" if prefix else f"{rest}\n"
        return f"{prefix}\n" if prefix else "\n"
    rendered = str(require_rust_binding("links_block_render")(table, None))
    wrapped = (
        f"<!-- sase:links:start -->\n\n{rendered.rstrip()}\n\n<!-- sase:links:end -->"
    )
    if prefix and rest:
        return f"{prefix}\n\n{wrapped}\n\n{rest}\n"
    if prefix:
        return f"{prefix}\n\n{wrapped}\n"
    if rest:
        return f"{wrapped}\n\n{rest}\n"
    return f"{wrapped}\n"


def _links_table(
    issue_id: str,
    rows: Sequence[Mapping[str, Any]],
    automatic_count: int,
    urls: Mapping[str, str],
) -> dict[str, Any]:
    pointer = None
    if automatic_count:
        pointer = (
            f"Plus {automatic_count} automatic references — see "
            "[Referenced By](#referenced-by)."
        )
    return {
        "schema_version": _LINKS_SCHEMA_VERSION,
        "columns": [dict(column) for column in _LINKS_COLUMNS],
        "rows": [_curated_row(issue_id, row, urls) for row in rows],
        "omitted": 0,
        **({"pointer": pointer} if pointer else {}),
    }


def _referenced_by_table(
    issue_id: str,
    rows: Sequence[Mapping[str, Any]],
    urls: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": _LINKS_SCHEMA_VERSION,
        "columns": [dict(column) for column in _REFERENCED_BY_COLUMNS],
        "rows": [_automatic_row(issue_id, row, urls) for row in rows],
        "omitted": 0,
    }


def _curated_row(
    issue_id: str, row: Mapping[str, Any], urls: Mapping[str, str]
) -> dict[str, Any]:
    relation, artifact = _perspective(issue_id, row)
    values = {
        "relation": relation,
        "artifact": artifact,
        "why": str(row.get("description") or ""),
    }
    payload: dict[str, Any] = {"values": values, "link_targets": {}}
    url = urls.get(artifact)
    if url:
        payload["link_targets"] = {"artifact": url}
    return payload


def _automatic_row(
    issue_id: str, row: Mapping[str, Any], urls: Mapping[str, str]
) -> dict[str, Any]:
    payload = _curated_row(issue_id, row, urls)
    payload["values"]["uses"] = str(int(row.get("uses") or 1))
    return payload


def _perspective(issue_id: str, row: Mapping[str, Any]) -> tuple[str, str]:
    canonical = f"bead:{issue_id}"
    source = str(row.get("source_ref") or "")
    target = str(row.get("target_ref") or "")
    relation = str(row.get("relation") or "")
    this_is_source = source == canonical
    other = target if this_is_source else source
    try:
        label = str(
            require_rust_binding("artifact_relation_label")(relation, this_is_source)
        )
    except (ValueError, TypeError, AttributeError):
        label = relation
    return label, other


__all__ = ["apply_bead_page_link_tables"]
