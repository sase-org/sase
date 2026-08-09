"""Per-Patch grouping keys and sort/walk helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sase.ace.patch import Patch
from sase.core.patch import strip_reverted_suffix
from sase.project_display_names import project_display_name_for

from ._buckets import (
    PatchGroupingMode,
    LatestTimestampMap,
    date_bucket_for_patch,
    date_bucket_sort_index,
    date_subgroup_for_patch,
    date_subgroup_sort_key,
    latest_from_map,
    status_bucket_for_patch,
    status_sort_index,
)


@dataclass(frozen=True)
class _PatchKeys:
    """Per-CS keys used to bucket and sort the tree.

    ``l0`` is the level-0 group label (project name in ``BY_PROJECT``,
    bucket name in ``BY_DATE`` / ``BY_STATUS``).  ``sibling_root`` is
    populated for modes that emit a sibling-root sub-banner
    (``BY_PROJECT`` and ``BY_STATUS``); ``date_subgroup`` is the BY_DATE
    L1 subgroup label (1-hour under Today/Yesterday, calendar day under
    This Week, Monday-start week under Earlier).
    """

    l0: str
    sibling_root: str
    date_subgroup: str = ""


def sibling_root_for_patch(cs: Patch) -> str:
    """Return the shared base name for ``foobar_1`` / ``foobar_2`` siblings.

    Reuses the existing ``strip_reverted_suffix`` helper so we don't
    invent fuzzier grouping than the current suffix scheme.  When the
    name has no suffix the root equals the name itself, which still
    lets singleton suppression collapse the L1 row.
    """
    return strip_reverted_suffix(cs.name)


def _l0_value_for(
    cs: Patch,
    mode: PatchGroupingMode,
    now: datetime,
    latest_map: LatestTimestampMap | None = None,
) -> str:
    if mode is PatchGroupingMode.BY_PROJECT:
        return project_display_name_for(cs.project_name)
    if mode is PatchGroupingMode.BY_DATE:
        return date_bucket_for_patch(cs, now, latest_map=latest_map)
    return status_bucket_for_patch(cs)


def keys_for_patch(
    cs: Patch,
    mode: PatchGroupingMode,
    now: datetime,
    latest_map: LatestTimestampMap | None = None,
) -> _PatchKeys:
    """Compute grouping keys for *cs* under *mode*."""
    l0 = _l0_value_for(cs, mode, now, latest_map=latest_map)
    return _PatchKeys(
        l0=l0,
        sibling_root=(
            sibling_root_for_patch(cs)
            if mode
            in (
                PatchGroupingMode.BY_PROJECT,
                PatchGroupingMode.BY_STATUS,
            )
            else ""
        ),
        date_subgroup=(
            date_subgroup_for_patch(cs, l0, latest_map=latest_map)
            if mode is PatchGroupingMode.BY_DATE
            else ""
        ),
    )


def keys_for_patches(
    patches: list[Patch],
    mode: PatchGroupingMode,
    now: datetime,
    latest_map: LatestTimestampMap | None = None,
) -> list[_PatchKeys]:
    return [keys_for_patch(cs, mode, now, latest_map=latest_map) for cs in patches]


def _l0_sort_key(mode: PatchGroupingMode, l0: str) -> tuple[int, object]:
    """Sort key for L0 banners.

    ``BY_PROJECT``: project name ascending (case-insensitive).
    ``BY_DATE``: fixed bucket order.
    ``BY_STATUS``: lifecycle order, then exact status text.
    """
    if mode is PatchGroupingMode.BY_PROJECT:
        return (0, l0.lower())
    if mode is PatchGroupingMode.BY_DATE:
        return (0, date_bucket_sort_index(l0))
    return (0, status_sort_index(l0))


def _date_anchor_for(cs: Patch, latest_map: LatestTimestampMap | None = None) -> float:
    """Return ``-epoch`` for the latest TIMESTAMPS entry, ``+inf`` if missing.

    Negated so newest sorts first when used inside a tuple sort key.
    """
    latest = latest_from_map(cs, latest_map)
    if latest is None:
        return float("inf")
    return -latest.timestamp()


def walk_order(
    patches: list[Patch],
    keys: list[_PatchKeys],
    mode: PatchGroupingMode,
    latest_map: LatestTimestampMap | None = None,
) -> list[int]:
    """Return a stable permutation of CS indices grouped by *mode*.

    * ``BY_PROJECT`` and ``BY_STATUS`` put singleton sibling roots before
      grouped roots within their L0 bucket so they render directly under
      the L0 banner.
    * ``BY_DATE`` sorts within bucket by latest timestamp descending.
    """
    # Count siblings per (l0, root) so singletons can sort first.
    root_counts: dict[tuple[str, str], int] = {}
    has_sibling_level = mode in (
        PatchGroupingMode.BY_PROJECT,
        PatchGroupingMode.BY_STATUS,
    )
    if has_sibling_level:
        for k in keys:
            root_counts[(k.l0, k.sibling_root)] = (
                root_counts.get((k.l0, k.sibling_root), 0) + 1
            )

    def sort_key(i: int) -> tuple[object, ...]:
        k = keys[i]
        l0 = _l0_sort_key(mode, k.l0)
        if has_sibling_level:
            in_group = root_counts.get((k.l0, k.sibling_root), 0) >= 2
            # ``(0, "")`` for singletons so they precede grouped roots,
            # then the lowercased root name groups same-root siblings
            # together; final ``i`` keeps within-root order stable.
            sibling = (1, k.sibling_root.lower()) if in_group else (0, "")
            return (l0, sibling, i)
        if mode is PatchGroupingMode.BY_DATE:
            latest = latest_from_map(patches[i], latest_map)
            subgroup = date_subgroup_sort_key(k.l0, k.date_subgroup, latest)
            return (
                l0,
                subgroup,
                _date_anchor_for(patches[i], latest_map),
                i,
            )
        return (l0, i)

    return sorted(range(len(patches)), key=sort_key)
