"""Shared, pane-agnostic grouping model for Artifacts panes.

Every Artifacts pane that owns a declared ``PaneGroupingModeDecl`` (Files,
Plans/Documents, Stitches, and — via its own fixed epic/phase shape — Beads)
renders the same kind of foldable banner row and walks the same kind of
navigation/jump index.  This module holds the pane-free pieces: the banner
record, the nested bucketing pass, and the stable navigation target for a
banner.  Rendering (turning a banner into an ``Option``) and registry
ownership (which pane/mode is collapsed) stay in the widget layer and the
app's action mixins respectively — this module has no Textual dependency.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from ..widgets.artifacts.entry_navigation import ArtifactEntryTarget
from .group_fold import GroupFoldRegistry, GroupKey

#: Leading marker for the ``parts`` of a banner's ``ArtifactEntryTarget`` so
#: it can never collide with a real row's target (real-row parts are
#: pane-specific identities that never start with this literal token).
GROUP_BANNER_MARKER = "__group__"


@dataclass(frozen=True, slots=True)
class ArtifactGroupBanner:
    """One foldable banner row shared across Artifacts panes."""

    pane_id: str
    mode_id: str
    group_key: GroupKey
    level: int
    label: str
    member_count: int
    collapsed: bool
    member_targets: tuple[ArtifactEntryTarget, ...] = field(default_factory=tuple)

    @property
    def target(self) -> ArtifactEntryTarget:
        """Return this banner's own stable navigation/jump identity."""
        return group_banner_target(self.pane_id, self.mode_id, self.group_key)

    @property
    def option_id(self) -> str:
        return group_banner_option_id(self.mode_id, self.group_key)


@dataclass(frozen=True, slots=True)
class _ArtifactGroupedRow[T]:
    """One row in a built grouped sequence — a banner or a member item."""

    kind: Literal["banner", "item"]
    banner: ArtifactGroupBanner | None = None
    item: T | None = None
    item_index: int | None = None


@dataclass(frozen=True, slots=True)
class ArtifactGroupBuildResult[T]:
    """Everything one grouped-row build pass produces."""

    rows: tuple[_ArtifactGroupedRow[T], ...]
    known_group_keys: tuple[GroupKey, ...]


def group_banner_target(
    pane_id: str,
    mode_id: str,
    group_key: GroupKey,
) -> ArtifactEntryTarget:
    """Return the stable ``ArtifactEntryTarget`` identity for one banner."""
    return ArtifactEntryTarget(
        pane_id=pane_id,
        parts=(GROUP_BANNER_MARKER, mode_id, *group_key),
    )


def group_banner_option_id(mode_id: str, group_key: GroupKey) -> str:
    """Return the stable OptionList id for one banner row."""
    return ":".join(("group", mode_id, *group_key))


def is_group_banner_target(target: ArtifactEntryTarget | None) -> bool:
    """Return whether *target* identifies a banner rather than a real row."""
    return (
        target is not None
        and len(target.parts) >= 2
        and target.parts[0] == GROUP_BANNER_MARKER
    )


def build_grouped_rows[T](
    items: Sequence[T],
    *,
    pane_id: str,
    mode_id: str,
    keys: tuple[str, ...],
    key_values: Callable[[T], tuple[str, ...]],
    label_for: Callable[[int, str], str],
    target_for: Callable[[T], ArtifactEntryTarget],
    fold_registry: GroupFoldRegistry | None = None,
) -> ArtifactGroupBuildResult[T]:
    """Bucket *items* into nested banner/item rows, clustering by group key.

    ``keys`` names one grouping level per entry (``("kind",)`` for a flat
    single-level mode, ``("kind", "tier")`` for a two-level one).
    ``key_values(item)`` must return one raw bucket value per level, in the
    same order as ``keys``.  Items with the same group key are always
    clustered under one banner, even when other groups' items are
    interleaved between them in the input — mirroring Patches'
    ``walk_order``.  Groups are ordered by the first index at which they
    appear, and items keep their relative input order within a group, so
    callers that pre-sorted (e.g. newest-first) keep that order both across
    and within groups.

    A collapsed banner at level ``L`` hides every deeper banner and every
    item under it; the walk still counts hidden members for the banner's
    ``member_count`` and ``member_targets``, since folding is a rendering
    decision, not a data-loss one.

    Returns the flat render-order row sequence plus the deduplicated list
    of every group key produced, for :meth:`GroupFoldRegistry.clear_unknown`.
    """
    n_levels = len(keys)
    if n_levels == 0 or not items:
        flat_rows = tuple(
            _ArtifactGroupedRow(kind="item", item=item, item_index=index)
            for index, item in enumerate(items)
        )
        return ArtifactGroupBuildResult(rows=flat_rows, known_group_keys=())

    registry = fold_registry if fold_registry is not None else GroupFoldRegistry()
    values = [key_values(item) for item in items]

    # First pass: every prefix path's member index list (in input order,
    # for counts/targets), each path's first-seen rank per level (so a
    # stable sort can cluster same-key items without otherwise reordering),
    # and each path's distinct child values one level down — a sub-level
    # whose parent has only one distinct child adds a banner that can never
    # actually subdivide anything, so it's suppressed (mirrors Patches'
    # singleton sibling-root suppression).
    member_indices: dict[GroupKey, list[int]] = {}
    first_seen_rank: dict[GroupKey, int] = {}
    children_by_parent: dict[GroupKey, set[str]] = {}
    for index, vals in enumerate(values):
        for level in range(n_levels):
            path: GroupKey = tuple(vals[: level + 1])
            member_indices.setdefault(path, []).append(index)
            if path not in first_seen_rank:
                first_seen_rank[path] = len(first_seen_rank)
            if level > 0:
                parent: GroupKey = tuple(vals[:level])
                children_by_parent.setdefault(parent, set()).add(vals[level])

    def _sort_key(index: int) -> tuple[int, ...]:
        vals = values[index]
        ranks = tuple(
            first_seen_rank[tuple(vals[: level + 1])] for level in range(n_levels)
        )
        return (*ranks, index)

    walk_order = sorted(range(len(items)), key=_sort_key)

    rows: list[_ArtifactGroupedRow[T]] = []
    known: list[GroupKey] = []
    seen: set[GroupKey] = set()
    current_path: list[str] = []
    collapsed_ancestor_level: int | None = None

    for index in walk_order:
        vals = values[index]
        divergence = next(
            (
                level
                for level in range(n_levels)
                if level >= len(current_path) or vals[level] != current_path[level]
            ),
            n_levels,
        )
        if divergence < n_levels:
            current_path = current_path[:divergence]
            if (
                collapsed_ancestor_level is not None
                and divergence <= collapsed_ancestor_level
            ):
                collapsed_ancestor_level = None
            for level in range(divergence, n_levels):
                path = tuple(vals[: level + 1])
                suppressed = (
                    level > 0
                    and len(children_by_parent.get(tuple(vals[:level]), ())) < 2
                )
                if not suppressed and path not in seen:
                    seen.add(path)
                    known.append(path)
                    if collapsed_ancestor_level is None:
                        member_idx = member_indices[path]
                        is_collapsed = registry.is_collapsed(path)
                        rows.append(
                            _ArtifactGroupedRow(
                                kind="banner",
                                banner=ArtifactGroupBanner(
                                    pane_id=pane_id,
                                    mode_id=mode_id,
                                    group_key=path,
                                    level=level,
                                    label=label_for(level, vals[level]),
                                    member_count=len(member_idx),
                                    collapsed=is_collapsed,
                                    member_targets=tuple(
                                        target_for(items[i]) for i in member_idx
                                    ),
                                ),
                            )
                        )
                        if is_collapsed:
                            collapsed_ancestor_level = level
                current_path.append(vals[level])
        if collapsed_ancestor_level is not None:
            continue
        rows.append(
            _ArtifactGroupedRow(kind="item", item=items[index], item_index=index)
        )

    return ArtifactGroupBuildResult(rows=tuple(rows), known_group_keys=tuple(known))


__all__ = [
    "GROUP_BANNER_MARKER",
    "ArtifactGroupBanner",
    "ArtifactGroupBuildResult",
    "build_grouped_rows",
    "group_banner_option_id",
    "group_banner_target",
    "is_group_banner_target",
]
