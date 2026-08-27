"""An O(1), app-owned index from a link-graph ref to its ordered chips.

Replaces the render-path O(n) scan every relation source pays through
``_known_target_for_ref``: this index is built once off the cached
:class:`~.artifact_links.ArtifactLinksSnapshot` (which already carries
projected rows -- see ``bead:sase-ug.3``), keyed by every alias spelling a
selected entity's ref might arrive in, so the render path is one
``dict.get`` (``bead:sase-ug.5``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import RLock
from typing import Any

from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    current_owner_agent_name_lookup_candidates,
)
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_store_support import (
    canonicalize_artifact_link_ref,
    is_projected_row,
)
from sase.sdd.artifact_link_neighborhood import SEMANTIC_RELATIONS

from .artifact_links import ArtifactLinksSnapshot, parse_link_ref, target_for_ref_kind
from .link_subject import accent_and_icon_for_ref


@dataclass(frozen=True, slots=True)
class LinkChip:
    """One typed edge from a subject's perspective, ready to display."""

    relation: str
    label: str
    directed: bool
    this_is_source: bool
    neighbor_ref: str
    neighbor_target: ArtifactEntryTarget | None
    accent: str
    icon: str
    why: str
    origin: str
    uses: int
    created_by: str
    created_at: str
    writable: bool


@dataclass(frozen=True, slots=True)
class LinkIndex:
    """App-owned O(1) index from a canonical ref to its ordered chips."""

    by_ref: Mapping[str, tuple[LinkChip, ...]]
    source_key: tuple[object, ...]

    def chips_for(self, ref: str) -> tuple[LinkChip, ...]:
        """Return *ref*'s ordered chips, or an empty tuple when it has none."""

        return self.by_ref.get(ref, ())


_INDEX_CACHE_LOCK = RLock()
_INDEX_CACHE: dict[tuple[object, ...], LinkIndex] = {}


def link_index_for_snapshot(snapshot: ArtifactLinksSnapshot) -> LinkIndex:
    """Return the cached :class:`LinkIndex` for *snapshot*, building it once.

    Gated by the snapshot's own ``source_key`` -- the same mtime+size
    aggregate signature :func:`.artifact_links.load_artifact_links_snapshot`
    already uses -- so a caller on the render path pays the build cost at
    most once per aggregate change.
    """

    key = snapshot.source_key
    with _INDEX_CACHE_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached is not None:
            return cached
    index = _build_link_index(snapshot)
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE[key] = index
    return index


def _build_link_index(snapshot: ArtifactLinksSnapshot) -> LinkIndex:
    """Build a fresh :class:`LinkIndex` from *snapshot*'s rows."""

    label_fn = require_rust_binding("artifact_relation_label")
    lookup_fn = require_rust_binding("artifact_relation_lookup")
    identity = AgentIdentitySnapshot.current()

    best_rows: dict[tuple[str, ...], dict[str, Any]] = {}
    order: list[tuple[str, ...]] = []
    for row in snapshot.rows:
        source_ref = str(row.get("source_ref") or "").strip()
        target_ref = str(row.get("target_ref") or "").strip()
        relation = str(row.get("relation") or "").strip()
        if not source_ref or not target_ref or not relation:
            continue
        directed = _directed(lookup_fn, relation)
        canon_source = _canonicalize(source_ref)
        canon_target = _canonicalize(target_ref)
        if directed:
            identity_key = ("d", canon_source, relation, canon_target)
        else:
            left, right = sorted((canon_source, canon_target))
            identity_key = ("u", relation, left, right)
        candidate = dict(row, source_ref=canon_source, target_ref=canon_target)
        existing = best_rows.get(identity_key)
        if existing is None:
            order.append(identity_key)
            best_rows[identity_key] = candidate
        elif _uses(candidate) > _uses(existing):
            best_rows[identity_key] = candidate

    grouped: dict[str, list[LinkChip]] = {}
    for key in order:
        row = best_rows[key]
        source_ref = str(row["source_ref"])
        target_ref = str(row["target_ref"])
        relation = str(row.get("relation") or "")
        directed = key[0] == "d"
        project_hint = row.get("_project")
        grouped.setdefault(source_ref, []).append(
            _build_chip(
                row,
                relation=relation,
                label_fn=label_fn,
                directed=directed,
                this_is_source=True,
                neighbor_ref=target_ref,
                project_hint=project_hint,
            )
        )
        grouped.setdefault(target_ref, []).append(
            _build_chip(
                row,
                relation=relation,
                label_fn=label_fn,
                directed=directed,
                this_is_source=False,
                neighbor_ref=source_ref,
                project_hint=project_hint,
            )
        )

    canonical: dict[str, tuple[LinkChip, ...]] = {
        ref: _ordered(chips) for ref, chips in grouped.items()
    }
    index: dict[str, tuple[LinkChip, ...]] = dict(canonical)
    for ref, chips in canonical.items():
        for alias in _aliases_for_ref(ref, identity):
            index.setdefault(alias, chips)

    return LinkIndex(by_ref=index, source_key=snapshot.source_key)


def _build_chip(
    row: Mapping[str, Any],
    *,
    relation: str,
    label_fn: Any,
    directed: bool,
    this_is_source: bool,
    neighbor_ref: str,
    project_hint: str | None,
) -> LinkChip:
    label = str(label_fn(relation, this_is_source))
    parsed = parse_link_ref(neighbor_ref)
    neighbor_kind = parsed[0] if parsed is not None else ""
    neighbor_target = (
        target_for_ref_kind(neighbor_kind, parsed[1], project_hint=project_hint)
        if parsed is not None
        else None
    )
    accent, icon = accent_and_icon_for_ref(neighbor_kind, neighbor_target)
    origin = str(row.get("origin") or "").strip()
    return LinkChip(
        relation=relation,
        label=label,
        directed=directed,
        this_is_source=this_is_source,
        neighbor_ref=neighbor_ref,
        neighbor_target=neighbor_target,
        accent=accent,
        icon=icon,
        why=str(row.get("description") or "").strip(),
        origin=origin,
        uses=_uses(row),
        created_by=str(row.get("created_by") or "").strip(),
        created_at=str(row.get("created_at") or "").strip(),
        writable=not is_projected_row(row),
    )


def _ordered(chips: Sequence[LinkChip]) -> tuple[LinkChip, ...]:
    """Sort chips the way ``neighborhood_footer`` already does.

    Semantic relations first, then everything else, each bucket ordered by
    label then neighbor ref -- so the rail, the audited-read footer, and the
    future ``$0`` panel can never disagree about chip order.
    """

    return tuple(
        sorted(
            chips,
            key=lambda chip: (
                chip.relation not in SEMANTIC_RELATIONS,
                chip.label,
                chip.neighbor_ref,
            ),
        )
    )


def _directed(lookup_fn: Any, relation: str) -> bool:
    try:
        info = lookup_fn(relation)
        return bool(info.get("directed", True))
    except (ValueError, TypeError, AttributeError):
        return relation != "related"


def _canonicalize(ref: str) -> str:
    try:
        return str(canonicalize_artifact_link_ref(ref))
    except Exception:  # noqa: BLE001 - a malformed ref degrades to itself, not a crash
        return ref


def _uses(row: Mapping[str, Any]) -> int:
    try:
        uses = int(row.get("uses") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, uses)


def _aliases_for_ref(ref: str, identity: AgentIdentitySnapshot) -> tuple[str, ...]:
    """Return extra spellings *ref* should also be reachable under.

    Mirrors ``_agent_ref_candidate_index``'s build-time alias pattern
    (``sase.agents.catalog._query``): every alias is a *pass-2*, first-wins
    key, never one that can shadow another edge's canonical spelling.
    """

    parsed = parse_link_ref(ref)
    if parsed is None:
        return ()
    kind, payload = parsed
    if kind == "agent":
        return tuple(
            f"agent:{candidate}"
            for candidate in current_owner_agent_name_lookup_candidates(
                payload, identity
            )
        )
    if kind == "stitch":
        repo, at, sha = payload.partition("@")
        if at and repo and len(sha) > 7:
            return (f"stitch:{repo}@{sha[:7]}",)
        return ()
    if kind == "plan":
        return (f"ref:plan:{payload}",)
    return ()


__all__ = [
    "LinkChip",
    "LinkIndex",
    "link_index_for_snapshot",
]
