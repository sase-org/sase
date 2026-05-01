"""Per-ChangeSpec grouping keys and sort/walk helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sase.ace.changespec import ChangeSpec
from sase.core.changespec import strip_reverted_suffix

from ._buckets import (
    ChangeSpecGroupingMode,
    LatestTimestampMap,
    date_bucket_for_changespec,
    date_bucket_sort_index,
    date_subgroup_for_changespec,
    date_subgroup_sort_key,
    latest_from_map,
    status_bucket_for_changespec,
    status_sort_index,
)


@dataclass(frozen=True)
class _ChangeSpecKeys:
    """Per-CS keys used to bucket and sort the tree.

    ``l0`` is the level-0 group label (project name in ``BY_PROJECT``,
    bucket name in ``BY_DATE`` / ``BY_STATUS``).  ``sibling_root`` is
    populated for modes that emit a sibling-root sub-banner
    (``BY_PROJECT`` and ``BY_STATUS``); ``date_subgroup`` is populated
    only for BY_DATE buckets that emit an L1 date subgroup.
    """

    l0: str
    sibling_root: str
    date_subgroup: str = ""


def sibling_root_for_changespec(cs: ChangeSpec) -> str:
    """Return the shared base name for ``foobar_1`` / ``foobar_2`` siblings.

    Reuses the existing ``strip_reverted_suffix`` helper so we don't
    invent fuzzier grouping than the current suffix scheme.  When the
    name has no suffix the root equals the name itself, which still
    lets singleton suppression collapse the L1 row.
    """
    return strip_reverted_suffix(cs.name)


def _l0_value_for(
    cs: ChangeSpec,
    mode: ChangeSpecGroupingMode,
    now: datetime,
    latest_map: LatestTimestampMap | None = None,
) -> str:
    if mode is ChangeSpecGroupingMode.BY_PROJECT:
        return cs.project_name
    if mode is ChangeSpecGroupingMode.BY_DATE:
        return date_bucket_for_changespec(cs, now, latest_map=latest_map)
    return status_bucket_for_changespec(cs)


def keys_for_changespec(
    cs: ChangeSpec,
    mode: ChangeSpecGroupingMode,
    now: datetime,
    latest_map: LatestTimestampMap | None = None,
) -> _ChangeSpecKeys:
    """Compute grouping keys for *cs* under *mode*."""
    l0 = _l0_value_for(cs, mode, now, latest_map=latest_map)
    return _ChangeSpecKeys(
        l0=l0,
        sibling_root=(
            sibling_root_for_changespec(cs)
            if mode
            in (
                ChangeSpecGroupingMode.BY_PROJECT,
                ChangeSpecGroupingMode.BY_STATUS,
            )
            else ""
        ),
        date_subgroup=(
            date_subgroup_for_changespec(cs, l0, latest_map=latest_map)
            if mode is ChangeSpecGroupingMode.BY_DATE
            else ""
        ),
    )


def keys_for_changespecs(
    changespecs: list[ChangeSpec],
    mode: ChangeSpecGroupingMode,
    now: datetime,
    latest_map: LatestTimestampMap | None = None,
) -> list[_ChangeSpecKeys]:
    return [
        keys_for_changespec(cs, mode, now, latest_map=latest_map) for cs in changespecs
    ]


def _l0_sort_key(mode: ChangeSpecGroupingMode, l0: str) -> tuple[int, object]:
    """Sort key for L0 banners.

    ``BY_PROJECT``: project name ascending (case-insensitive).
    ``BY_DATE``: fixed bucket order.
    ``BY_STATUS``: lifecycle order, then exact status text.
    """
    if mode is ChangeSpecGroupingMode.BY_PROJECT:
        return (0, l0.lower())
    if mode is ChangeSpecGroupingMode.BY_DATE:
        return (0, date_bucket_sort_index(l0))
    return (0, status_sort_index(l0))


def _date_anchor_for(
    cs: ChangeSpec, latest_map: LatestTimestampMap | None = None
) -> float:
    """Return ``-epoch`` for the latest TIMESTAMPS entry, ``+inf`` if missing.

    Negated so newest sorts first when used inside a tuple sort key.
    """
    latest = latest_from_map(cs, latest_map)
    if latest is None:
        return float("inf")
    return -latest.timestamp()


def walk_order(
    changespecs: list[ChangeSpec],
    keys: list[_ChangeSpecKeys],
    mode: ChangeSpecGroupingMode,
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
        ChangeSpecGroupingMode.BY_PROJECT,
        ChangeSpecGroupingMode.BY_STATUS,
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
        if mode is ChangeSpecGroupingMode.BY_DATE:
            latest = latest_from_map(changespecs[i], latest_map)
            subgroup = date_subgroup_sort_key(k.l0, k.date_subgroup, latest)
            return (l0, subgroup, _date_anchor_for(changespecs[i], latest_map), i)
        return (l0, i)

    return sorted(range(len(changespecs)), key=sort_key)
