"""Tree builder and banner row records for ChangeSpec grouping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sase.ace.changespec import ChangeSpec

from ..group_fold import GroupFoldRegistry, GroupKey
from ._buckets import ChangeSpecGroupingMode, precompute_latest_timestamps
from ._keys import keys_for_changespec, keys_for_changespecs, walk_order


@dataclass(frozen=True)
class ChangeSpecGroupRow:
    """A banner row in the grouped CL tree.

    ``level`` is 0 for project / date / status banners, 1 for a
    sibling-root or first BY_DATE subgroup, and 2 for the hourly BY_DATE
    subgroup under Today / Yesterday.
    ``changespec_indices`` references the input ``changespecs`` list so
    callers can show counts or jump to the first member.
    """

    level: int
    group_key: GroupKey
    changespec_indices: tuple[int, ...]
    is_collapsed: bool = False


@dataclass(frozen=True)
class ChangeSpecTreeEntry:
    """One row in the rendered tree — either a banner or a CL."""

    kind: str  # "group" or "changespec"
    group: ChangeSpecGroupRow | None = None
    changespec_idx: int | None = None


def _should_emit_hour_subgroup(parent_count: int, hour: str) -> bool:
    """Whether a BY_DATE one-hour subgroup should have a visible banner."""
    return bool(hour) and parent_count >= 2


def enumerate_changespec_group_keys(
    changespecs: list[ChangeSpec],
    mode: ChangeSpecGroupingMode = ChangeSpecGroupingMode.BY_PROJECT,
    now: datetime | None = None,
) -> list[GroupKey]:
    """Return the deduplicated list of every banner key produced by *mode*.

    Sibling-root L1 keys are only included when their root has 2+ visible
    CLs, matching the suppression rule in :func:`build_changespec_tree`.
    BY_DATE L1 keys are included for non-empty first-level subgroups;
    hourly L2 keys are included under Today / Yesterday 4-hour headings.
    """
    if not changespecs:
        return []
    reference = now if now is not None else datetime.now()
    # BY_DATE bucketing reads the latest TIMESTAMPS entry; precomputing
    # once keeps enumeration linear instead of re-parsing per CS.
    latest_map = (
        precompute_latest_timestamps(changespecs)
        if mode is ChangeSpecGroupingMode.BY_DATE
        else None
    )
    keys = keys_for_changespecs(changespecs, mode, reference, latest_map=latest_map)
    walk = walk_order(changespecs, keys, mode, latest_map=latest_map)

    seen: set[GroupKey] = set()
    out: list[GroupKey] = []
    has_sibling_level = mode in (
        ChangeSpecGroupingMode.BY_PROJECT,
        ChangeSpecGroupingMode.BY_STATUS,
    )
    if has_sibling_level:
        root_counts: dict[tuple[str, str], int] = {}
        for i in walk:
            k = keys[i]
            root_counts[(k.l0, k.sibling_root)] = (
                root_counts.get((k.l0, k.sibling_root), 0) + 1
            )
        for i in walk:
            k = keys[i]
            l0_key: GroupKey = (k.l0,)
            if l0_key not in seen:
                seen.add(l0_key)
                out.append(l0_key)
            if root_counts.get((k.l0, k.sibling_root), 0) >= 2:
                deep: GroupKey = (k.l0, k.sibling_root)
                if deep not in seen:
                    seen.add(deep)
                    out.append(deep)
    elif mode is ChangeSpecGroupingMode.BY_DATE:
        date_subgroup_counts: dict[tuple[str, str], int] = {}
        for i in walk:
            k = keys[i]
            if k.date_subgroup:
                date_subgroup_counts[(k.l0, k.date_subgroup)] = (
                    date_subgroup_counts.get((k.l0, k.date_subgroup), 0) + 1
                )
        for i in walk:
            k = keys[i]
            l0_key = (k.l0,)
            if l0_key not in seen:
                seen.add(l0_key)
                out.append(l0_key)
            if k.date_subgroup:
                deep = (k.l0, k.date_subgroup)
                if deep not in seen:
                    seen.add(deep)
                    out.append(deep)
            parent_count = date_subgroup_counts.get((k.l0, k.date_subgroup), 0)
            if _should_emit_hour_subgroup(parent_count, k.hour_subgroup):
                hourly = (k.l0, k.date_subgroup, k.hour_subgroup)
                if hourly not in seen:
                    seen.add(hourly)
                    out.append(hourly)
    else:
        for i in walk:
            k = keys[i]
            l0_key = (k.l0,)
            if l0_key not in seen:
                seen.add(l0_key)
                out.append(l0_key)
    return out


def build_changespec_tree(
    changespecs: list[ChangeSpec],
    mode: ChangeSpecGroupingMode = ChangeSpecGroupingMode.BY_PROJECT,
    fold_registry: GroupFoldRegistry | None = None,
    now: datetime | None = None,
) -> list[ChangeSpecTreeEntry]:
    """Build the grouped tree of banner + CL entries.

    Args:
        changespecs: Filtered CL list.
        mode: Grouping strategy.
        fold_registry: Optional per-group collapse registry.  Missing or
            empty registry renders every group expanded.
        now: Reference time for ``BY_DATE`` (defaults to ``datetime.now()``).

    Returns:
        Flat list of :class:`ChangeSpecTreeEntry` rows in render order.
    """
    if not changespecs:
        return []

    registry = fold_registry if fold_registry is not None else GroupFoldRegistry()
    reference = now if now is not None else datetime.now()
    # BY_DATE uses the latest TIMESTAMPS entry both for L0 bucketing and
    # for the within-bucket sort anchor; precompute once so a 200-CL
    # refresh does 200 timestamp parses, not 600.
    latest_map = (
        precompute_latest_timestamps(changespecs)
        if mode is ChangeSpecGroupingMode.BY_DATE
        else None
    )
    keys = [
        keys_for_changespec(cs, mode, reference, latest_map=latest_map)
        for cs in changespecs
    ]
    walk = walk_order(changespecs, keys, mode, latest_map=latest_map)

    has_sibling_level = mode in (
        ChangeSpecGroupingMode.BY_PROJECT,
        ChangeSpecGroupingMode.BY_STATUS,
    )
    has_date_subgroups = mode is ChangeSpecGroupingMode.BY_DATE
    l0_indices: dict[str, list[int]] = {}
    root_indices: dict[tuple[str, str], list[int]] = {}
    date_subgroup_indices: dict[tuple[str, str], list[int]] = {}
    hour_subgroup_indices: dict[tuple[str, str, str], list[int]] = {}
    for i in walk:
        k = keys[i]
        l0_indices.setdefault(k.l0, []).append(i)
        if has_sibling_level and k.sibling_root:
            root_indices.setdefault((k.l0, k.sibling_root), []).append(i)
        if has_date_subgroups and k.date_subgroup:
            date_subgroup_indices.setdefault((k.l0, k.date_subgroup), []).append(i)
        if has_date_subgroups and k.hour_subgroup:
            hour_subgroup_indices.setdefault(
                (k.l0, k.date_subgroup, k.hour_subgroup), []
            ).append(i)

    entries: list[ChangeSpecTreeEntry] = []
    cur_l0: str | None = None
    cur_l0_collapsed = False
    cur_root: str = ""
    cur_root_collapsed = False
    cur_date_subgroup: str = ""
    cur_date_subgroup_collapsed = False
    cur_hour_subgroup: str = ""
    cur_hour_subgroup_collapsed = False

    for i in walk:
        k = keys[i]
        if cur_l0 is None or k.l0 != cur_l0:
            l0_key: GroupKey = (k.l0,)
            cur_l0_collapsed = registry.is_collapsed(l0_key)
            entries.append(
                ChangeSpecTreeEntry(
                    kind="group",
                    group=ChangeSpecGroupRow(
                        level=0,
                        group_key=l0_key,
                        changespec_indices=tuple(l0_indices[k.l0]),
                        is_collapsed=cur_l0_collapsed,
                    ),
                )
            )
            cur_l0 = k.l0
            cur_root = ""
            cur_root_collapsed = False
            cur_date_subgroup = ""
            cur_date_subgroup_collapsed = False
            cur_hour_subgroup = ""
            cur_hour_subgroup_collapsed = False
        if cur_l0_collapsed:
            continue

        if has_date_subgroups and k.date_subgroup:
            if k.date_subgroup != cur_date_subgroup:
                cur_date_subgroup = k.date_subgroup
                cur_hour_subgroup = ""
                cur_hour_subgroup_collapsed = False
                date_subgroup_key: GroupKey = (k.l0, k.date_subgroup)
                cur_date_subgroup_collapsed = registry.is_collapsed(date_subgroup_key)
                entries.append(
                    ChangeSpecTreeEntry(
                        kind="group",
                        group=ChangeSpecGroupRow(
                            level=1,
                            group_key=date_subgroup_key,
                            changespec_indices=tuple(
                                date_subgroup_indices[(k.l0, k.date_subgroup)]
                            ),
                            is_collapsed=cur_date_subgroup_collapsed,
                        ),
                    )
                )
        else:
            cur_date_subgroup = ""
            cur_date_subgroup_collapsed = False
            cur_hour_subgroup = ""
            cur_hour_subgroup_collapsed = False

        if cur_date_subgroup_collapsed:
            continue

        if has_date_subgroups and k.hour_subgroup:
            parent_count = len(date_subgroup_indices[(k.l0, k.date_subgroup)])
            if _should_emit_hour_subgroup(parent_count, k.hour_subgroup):
                if k.hour_subgroup != cur_hour_subgroup:
                    cur_hour_subgroup = k.hour_subgroup
                    hour_index_key = (k.l0, k.date_subgroup, k.hour_subgroup)
                    hour_key: GroupKey = hour_index_key
                    cur_hour_subgroup_collapsed = registry.is_collapsed(hour_index_key)
                    entries.append(
                        ChangeSpecTreeEntry(
                            kind="group",
                            group=ChangeSpecGroupRow(
                                level=2,
                                group_key=hour_key,
                                changespec_indices=tuple(
                                    hour_subgroup_indices[hour_index_key]
                                ),
                                is_collapsed=cur_hour_subgroup_collapsed,
                            ),
                        )
                    )
            else:
                cur_hour_subgroup = ""
                cur_hour_subgroup_collapsed = False
        else:
            cur_hour_subgroup = ""
            cur_hour_subgroup_collapsed = False

        if cur_hour_subgroup_collapsed:
            continue

        if has_sibling_level and k.sibling_root:
            siblings = root_indices.get((k.l0, k.sibling_root), [])
            if len(siblings) >= 2 and k.sibling_root != cur_root:
                cur_root = k.sibling_root
                deep_key: GroupKey = (k.l0, k.sibling_root)
                cur_root_collapsed = registry.is_collapsed(deep_key)
                entries.append(
                    ChangeSpecTreeEntry(
                        kind="group",
                        group=ChangeSpecGroupRow(
                            level=1,
                            group_key=deep_key,
                            changespec_indices=tuple(siblings),
                            is_collapsed=cur_root_collapsed,
                        ),
                    )
                )
            elif len(siblings) < 2:
                # Singleton root: no L1 banner; reset the collapse-state
                # tracking so a subsequent grouped root re-emits its banner.
                cur_root = ""
                cur_root_collapsed = False
        else:
            cur_root = ""
            cur_root_collapsed = False

        if cur_root_collapsed:
            continue
        entries.append(ChangeSpecTreeEntry(kind="changespec", changespec_idx=i))

    return entries
