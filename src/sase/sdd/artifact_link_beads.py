"""Bead-store truth for typed artifact links.

Sidecar ``links/`` JSON never owns ``bead:`` rows. Every bead endpoint of a
row gets its own ``LinkAdded`` / ``LinkRemoved`` event on its own stream:
``direction="out"`` when the bead is the row's source, ``direction="in"``
when it is the target. A row with a bead in both positions is stored on
both beads; the duplicate canonical row that produces collapses under
``unique_rows``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.bead.model import BeadLink, Issue
from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
)


def bead_id_from_ref(value: str) -> str | None:
    """Return the bead id inside a canonical ``bead:`` ref, if any."""

    canonical = str(require_rust_binding("artifact_link_canonicalize")(value))
    kind, _sep, rest = canonical.partition(":")
    if kind != "bead" or not rest:
        return None
    return rest


def bead_source_ref(issue_id: str) -> str:
    """Return the canonical ``bead:<id>`` source ref."""

    return f"bead:{issue_id}"


def add_bead_endpoint_link(
    beads_dir: Path,
    *,
    issue_id: str,
    target_ref: str,
    relation: str,
    description: str,
    origin: str,
    direction: str = "out",
    uses: int = 1,
    now: str | None = None,
) -> dict[str, Any]:
    """Write one LinkAdded event.

    *direction* is ``"out"`` when *issue_id* is the row's source (the
    historical shape) and ``"in"`` when it is the row's target. *target_ref*
    always names the other endpoint regardless of direction. *uses* seeds a
    brand-new stored link; a rewrite of an existing one ignores it and
    increments the existing count instead, mirroring the aggregate's own
    upsert semantics.
    """
    from sase.core import bead_mutation_facade as rust_beads

    _issue, outcome = rust_beads.add_link(
        beads_dir,
        issue_id,
        target_ref,
        relation,
        description,
        origin=origin,
        direction=direction,
        uses=uses,
        now=now,
    )
    return outcome


def remove_bead_endpoint_link(
    beads_dir: Path,
    *,
    issue_id: str,
    target_ref: str,
    relation: str | None,
    direction: str = "out",
    now: str | None = None,
) -> dict[str, Any]:
    """Write LinkRemoved events."""
    from sase.core import bead_mutation_facade as rust_beads

    _issue, outcome = rust_beads.remove_link(
        beads_dir,
        issue_id,
        target_ref,
        relation=relation,
        direction=direction,
        now=now,
    )
    return outcome


def rows_from_bead_issues(
    issues: Sequence[Issue],
    *,
    created_by: str = "bead-store",
    created_at: str = "1970-01-01T00:00:00Z",
) -> tuple[dict[str, Any], ...]:
    """Project stored bead links into v2 aggregate rows.

    A link stored with ``direction="in"`` has the owning bead in the
    target position, so it projects back into canonical order: the stored
    ``target_ref`` (the other endpoint) becomes the row's ``source_ref``,
    and the owning bead becomes the row's ``target_ref``.
    """

    rows: list[dict[str, Any]] = []
    for issue in issues:
        own_ref = bead_source_ref(issue.id)
        stamp = issue.updated_at or issue.created_at or created_at
        actor = issue.owner or issue.created_by or created_by
        for link in issue.links:
            rows.append(
                _row_from_bead_link(
                    own_ref=own_ref,
                    link=link,
                    created_by=actor,
                    created_at=stamp,
                )
            )
    return tuple(rows)


def rows_touching_bead(
    issues: Sequence[Issue],
    issue_id: str,
    *,
    extra_rows: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    """Return every v2 row that touches ``bead:<issue_id>``, both directions."""

    canonical = bead_source_ref(issue_id)
    collected: list[dict[str, Any]] = [
        dict(row)
        for row in rows_from_bead_issues(issues)
        if _row_touches(row, canonical)
    ]
    for row in extra_rows:
        payload = dict(row)
        if _row_touches(payload, canonical):
            collected.append(payload)
    return tuple(_unique_rows(collected))


def _row_from_bead_link(
    *,
    own_ref: str,
    link: BeadLink,
    created_by: str,
    created_at: str,
) -> dict[str, Any]:
    if link.direction == "in":
        source_ref, target_ref = link.target_ref, own_ref
    else:
        source_ref, target_ref = own_ref, link.target_ref
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": source_ref,
        "relation": link.relation,
        "target_ref": target_ref,
        "description": link.description,
        "origin": link.origin,
        "created_by": created_by or "bead-store",
        "created_at": created_at or "1970-01-01T00:00:00Z",
        "uses": link.uses,
    }


def _row_touches(row: Mapping[str, Any], artifact_ref: str) -> bool:
    return artifact_ref in {
        str(row.get("source_ref") or ""),
        str(row.get("target_ref") or ""),
    }


def _row_identity(row: Mapping[str, Any]) -> tuple[str, ...]:
    relation = str(row.get("relation") or "")
    source = str(row.get("source_ref") or "")
    target = str(row.get("target_ref") or "")
    directed = True
    try:
        looked_up = require_rust_binding("artifact_relation_lookup")(relation)
        directed = bool(looked_up.get("directed", True))
    except (ValueError, TypeError, AttributeError):
        directed = relation != "related"
    if directed:
        return ("directed", source, relation, target)
    left, right = sorted((source, target))
    return ("undirected", relation, left, right)


def _unique_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, ...], dict[str, Any]] = {}
    order: list[tuple[str, ...]] = []
    for row in rows:
        identity = _row_identity(row)
        if identity in seen:
            continue
        seen[identity] = dict(row)
        order.append(identity)
    return [seen[key] for key in order]


__all__ = [
    "add_bead_endpoint_link",
    "bead_id_from_ref",
    "bead_source_ref",
    "remove_bead_endpoint_link",
    "rows_from_bead_issues",
    "rows_touching_bead",
]
