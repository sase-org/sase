"""One-hop typed artifact-link neighborhood helpers.

Shared by ``sase artifact read``'s discovery footer and the launch-prompt
one-hop expansion, so both surfaces agree on how a stored row projects to a
typed, directional label from one artifact's perspective.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_store import resolve_artifact_link_store


# Registry relations whose rows assert meaning (`written_by: cli` in the
# relation registry) rather than recording agent behavior.
SEMANTIC_RELATIONS = frozenset({"related", "supersedes", "implements", "derives-from"})
# The subset judged worth auto-expanding into a launch prompt: directed,
# high-signal semantic edges. `related` is undirected and imprecise enough to
# stay out of automatic context; observational edges (`read`, `cites`) record
# agent behavior, not meaning.
LAUNCH_NEIGHBORHOOD_RELATIONS = frozenset({"implements", "derives-from", "supersedes"})

_FOOTER_MAX_ITEMS = 5
_LAUNCH_MAX_ITEMS = 5


def load_neighborhood_rows(canonical_ref: str) -> tuple[dict[str, Any], ...]:
    """Return every stored link row touching *canonical_ref*, best-effort."""

    try:
        store = resolve_artifact_link_store()
        return tuple(store.load_artifact_rows(canonical_ref))
    except Exception:  # noqa: BLE001 - neighborhood lookup must not break callers
        return ()


def _labeled_neighbors(
    canonical_ref: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, str, str], ...]:
    """Return ``(relation, label, neighbor)`` from *canonical_ref*'s perspective."""

    label_fn = require_rust_binding("artifact_relation_label")
    items: list[tuple[str, str, str]] = []
    for row in rows:
        source = str(row.get("source_ref") or "")
        target = str(row.get("target_ref") or "")
        if canonical_ref not in (source, target):
            continue
        this_is_source = source == canonical_ref
        neighbor = target if this_is_source else source
        relation = str(row.get("relation") or "")
        label = str(label_fn(relation, this_is_source))
        items.append((relation, label, neighbor))
    return tuple(items)


def neighborhood_footer(
    canonical_ref: str,
    rows: Sequence[Mapping[str, Any]],
) -> str | None:
    """Build the one-line ``Links: ...`` footer for an audited read, or ``None``."""

    labeled = _labeled_neighbors(canonical_ref, rows)
    if not labeled:
        return None
    ordered = sorted(
        labeled,
        key=lambda item: (item[0] not in SEMANTIC_RELATIONS, item[1], item[2]),
    )
    shown = ordered[:_FOOTER_MAX_ITEMS]
    overflow = len(ordered) - len(shown)
    line = "Links: " + " · ".join(f"{label} {neighbor}" for _, label, neighbor in shown)
    if overflow:
        line += f" (+{overflow} more)"
    return line


def superseded_by_refs(
    canonical_ref: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return the refs that supersede *canonical_ref*, if any."""

    refs = {
        str(row.get("source_ref") or "")
        for row in rows
        if str(row.get("relation") or "") == "supersedes"
        and str(row.get("target_ref") or "") == canonical_ref
    }
    return tuple(sorted(refs))


def launch_one_hop_neighborhood(
    canonical_ref: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return typed ``<label> <neighbor>`` strings for launch-prompt expansion.

    Filtered to directed semantic relations only and capped: this feeds an
    agent's context automatically, so it stays small and never expands past
    one hop.
    """

    labeled = _labeled_neighbors(canonical_ref, rows)
    semantic = [item for item in labeled if item[0] in LAUNCH_NEIGHBORHOOD_RELATIONS]
    ordered = sorted(semantic, key=lambda item: (item[1], item[2]))
    return tuple(
        f"{label} {neighbor}" for _, label, neighbor in ordered[:_LAUNCH_MAX_ITEMS]
    )


__all__ = [
    "LAUNCH_NEIGHBORHOOD_RELATIONS",
    "SEMANTIC_RELATIONS",
    "launch_one_hop_neighborhood",
    "load_neighborhood_rows",
    "neighborhood_footer",
    "superseded_by_refs",
]
