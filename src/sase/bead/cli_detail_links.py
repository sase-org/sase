"""Presentation view of a bead's typed artifact-link neighborhood."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sase.core.bead_read_facade import BeadArtifactLinkRow
from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_beads import rows_from_bead_issues
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    resolve_artifact_link_store,
)

LinkDirection = Literal["outgoing", "incoming", "symmetric"]
LinkSection = Literal["links", "referenced_by"]

_REFERENCED_BY_ORIGINS = frozenset({"prompt_ref", "prompt_prose", "read"})
_ORIGIN_LABELS = {
    "prompt_ref": "prompt citation",
    "prompt_prose": "prose citation",
    "read": "audited read",
}
_GLYPHS = {
    "outgoing": "→",
    "incoming": "←",
    "symmetric": "↔",
}

NO_LINKS_RECOVERY_HINT = (
    "rerun with --no-links to show the rest of this bead without resolving "
    "artifact links"
)


@dataclass(frozen=True)
class BeadLinkView:
    """One neighborhood row from the displayed bead's perspective."""

    source_ref: str
    target_ref: str
    relation: str
    displayed_relation: str
    direction: LinkDirection
    counterpart_ref: str
    reason: str
    origin: str
    origin_label: str
    actor: str
    timestamp: str
    uses: int
    section: LinkSection

    @property
    def glyph(self) -> str:
        return _GLYPHS[self.direction]


def _project_bead_link_views(
    *,
    bead_id: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[BeadLinkView, ...]:
    """Project validated graph rows into the current bead's perspective."""

    canonical = f"bead:{bead_id}"
    views = [_view_from_row(canonical, row) for row in rows]
    views.sort(
        key=lambda view: (
            0 if view.section == "links" else 1,
            view.displayed_relation,
            view.counterpart_ref,
            view.timestamp,
            view.source_ref,
            view.target_ref,
            view.relation,
        )
    )
    return tuple(views)


def assemble_bead_link_neighborhood(
    *,
    bead_id: str,
    bead_owned_rows: Sequence[BeadArtifactLinkRow] | Sequence[Mapping[str, Any]] = (),
    fallback_issue: Any | None = None,
) -> tuple[BeadLinkView, ...]:
    """Merge bead-owned, sidecar, and aggregate-only rows for one bead.

    Missing optional sidecars are not an error. A present but malformed or
    unsupported link index is raised to the caller.
    """

    owned = _owned_row_dicts(bead_owned_rows)
    if not owned and fallback_issue is not None:
        owned = [dict(row) for row in rows_from_bead_issues((fallback_issue,))]
    store = _optional_artifact_link_store()
    if store is None:
        rows: Sequence[Mapping[str, Any]] = owned
    else:
        rows = store.load_artifact_rows(
            f"bead:{bead_id}",
            bead_owned_rows=owned,
        )
    return _project_bead_link_views(bead_id=bead_id, rows=rows)


def _origin_label(origin: str) -> str:
    """Return the friendly origin label, or the raw stored value."""

    key = origin.strip()
    if not key:
        return ""
    return _ORIGIN_LABELS.get(key, key)


def uses_label(uses: int) -> str:
    """Return the accumulated-use fragment for referenced-by rows."""

    noun = "use" if uses == 1 else "uses"
    return f"{uses} {noun}"


def _owned_row_dicts(
    rows: Sequence[BeadArtifactLinkRow] | Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, BeadArtifactLinkRow):
            payload = row.as_row_dict()
            payload["schema_version"] = ARTIFACT_LINK_ROW_SCHEMA_VERSION
            converted.append(payload)
        else:
            converted.append(dict(row))
    return converted


def _optional_artifact_link_store() -> Any | None:
    try:
        return resolve_artifact_link_store()
    except (OSError, RuntimeError, ValueError):
        return None


def _view_from_row(canonical: str, row: Mapping[str, Any]) -> BeadLinkView:
    source_ref = str(row.get("source_ref") or "")
    target_ref = str(row.get("target_ref") or "")
    relation = str(row.get("relation") or "")
    this_is_source = source_ref == canonical
    directed, displayed = _relation_perspective(relation, this_is_source)
    if not directed:
        direction: LinkDirection = "symmetric"
    elif this_is_source:
        direction = "outgoing"
    else:
        direction = "incoming"
    origin = str(row.get("origin") or "")
    try:
        uses = int(row.get("uses") or 1)
    except (TypeError, ValueError):
        uses = 1
    return BeadLinkView(
        source_ref=source_ref,
        target_ref=target_ref,
        relation=relation,
        displayed_relation=displayed,
        direction=direction,
        counterpart_ref=target_ref if this_is_source else source_ref,
        reason=str(row.get("description") or ""),
        origin=origin,
        origin_label=_origin_label(origin) or origin,
        actor=str(row.get("created_by") or ""),
        timestamp=str(row.get("created_at") or ""),
        uses=uses if uses > 0 else 1,
        section=("referenced_by" if origin in _REFERENCED_BY_ORIGINS else "links"),
    )


def _relation_perspective(relation: str, this_is_source: bool) -> tuple[bool, str]:
    try:
        looked_up = require_rust_binding("artifact_relation_lookup")(relation)
        directed = bool(looked_up.get("directed", True))
        displayed = str(
            require_rust_binding("artifact_relation_label")(relation, this_is_source)
        )
        return directed, displayed
    except (ValueError, TypeError, AttributeError):
        directed = relation != "related"
        return directed, relation


__all__ = [
    "BeadLinkView",
    "NO_LINKS_RECOVERY_HINT",
    "assemble_bead_link_neighborhood",
    "uses_label",
]
