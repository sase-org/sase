"""Tree builder and banner row records for Patch grouping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sase.ace.patch import Patch
from sase.core.time import local_now

from ..group_fold import GroupFoldRegistry, GroupKey
from ._buckets import PatchGroupingMode, precompute_latest_timestamps
from ._keys import keys_for_patch, keys_for_patches, walk_order


@dataclass(frozen=True, init=False)
class PatchGroupRow:
    """A banner row in the grouped PR tree.

    ``level`` is 0 for project / date / status banners and 1 for a
    sibling-root or BY_DATE subgroup.
    ``patch_indices`` references the input ``patches`` list so
    callers can show counts or jump to the first member.
    """

    level: int
    group_key: GroupKey
    patch_indices: tuple[int, ...]
    changespec_indices: tuple[int, ...]  # legacy compatibility alias
    is_collapsed: bool = False

    def __init__(
        self,
        *,
        level: int,
        group_key: GroupKey,
        patch_indices: tuple[int, ...] = (),
        changespec_indices: tuple[int, ...] = (),  # legacy compatibility alias
        is_collapsed: bool = False,
    ) -> None:
        indices = (
            patch_indices if patch_indices else changespec_indices
        )  # legacy compatibility alias
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "group_key", group_key)
        object.__setattr__(self, "patch_indices", indices)
        object.__setattr__(
            self, "changespec_indices", indices
        )  # legacy compatibility alias
        object.__setattr__(self, "is_collapsed", is_collapsed)


@dataclass(frozen=True, init=False)
class PatchTreeEntry:
    """One row in the rendered tree — either a banner or a Patch."""

    kind: str  # "group" or "patch"
    group: PatchGroupRow | None = None
    patch_idx: int | None = None
    changespec_idx: int | None = None  # legacy compatibility alias

    def __init__(
        self,
        *,
        kind: str,
        group: PatchGroupRow | None = None,
        patch_idx: int | None = None,
        changespec_idx: int | None = None,  # legacy compatibility alias
    ) -> None:
        idx = (
            patch_idx if patch_idx is not None else changespec_idx
        )  # legacy compatibility alias
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "group", group)
        object.__setattr__(self, "patch_idx", idx)
        object.__setattr__(self, "changespec_idx", idx)  # legacy compatibility alias


def enumerate_patch_group_keys(
    patches: list[Patch],
    mode: PatchGroupingMode = PatchGroupingMode.BY_PROJECT,
    now: datetime | None = None,
) -> list[GroupKey]:
    """Return the deduplicated list of every banner key produced by *mode*.

    Sibling-root L1 keys are only included when their root has 2+ visible
    Patches, matching the suppression rule in :func:`build_patch_tree`.
    BY_DATE L1 keys are included for non-empty subgroups (1-hour under
    Today / Yesterday, calendar day under This Week, Monday-start week
    under Earlier).
    """
    if not patches:
        return []
    reference = now if now is not None else local_now()
    # BY_DATE bucketing reads the latest TIMESTAMPS entry; precomputing
    # once keeps enumeration linear instead of re-parsing per CS.
    latest_map = (
        precompute_latest_timestamps(patches)
        if mode is PatchGroupingMode.BY_DATE
        else None
    )
    keys = keys_for_patches(patches, mode, reference, latest_map=latest_map)
    walk = walk_order(patches, keys, mode, latest_map=latest_map)

    seen: set[GroupKey] = set()
    out: list[GroupKey] = []
    has_sibling_level = mode in (
        PatchGroupingMode.BY_PROJECT,
        PatchGroupingMode.BY_STATUS,
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
    elif mode is PatchGroupingMode.BY_DATE:
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
    else:
        for i in walk:
            k = keys[i]
            l0_key = (k.l0,)
            if l0_key not in seen:
                seen.add(l0_key)
                out.append(l0_key)
    return out


def build_patch_tree(
    patches: list[Patch],
    mode: PatchGroupingMode = PatchGroupingMode.BY_PROJECT,
    fold_registry: GroupFoldRegistry | None = None,
    now: datetime | None = None,
) -> list[PatchTreeEntry]:
    """Build the grouped tree of banner + PR entries.

    Args:
        patches: Filtered Patch list.
        mode: Grouping strategy.
        fold_registry: Optional per-group collapse registry.  Missing or
            empty registry renders every group expanded.
        now: Reference time for ``BY_DATE`` (defaults to ``datetime.now()``).

    Returns:
        Flat list of :class:`PatchTreeEntry` rows in render order.
    """
    if not patches:
        return []

    registry = fold_registry if fold_registry is not None else GroupFoldRegistry()
    reference = now if now is not None else local_now()
    # BY_DATE uses the latest TIMESTAMPS entry both for L0 bucketing and
    # for the within-bucket sort anchor; precompute once so a 200-Patch
    # refresh does 200 timestamp parses, not 600.
    latest_map = (
        precompute_latest_timestamps(patches)
        if mode is PatchGroupingMode.BY_DATE
        else None
    )
    keys = [
        keys_for_patch(cs, mode, reference, latest_map=latest_map) for cs in patches
    ]
    walk = walk_order(patches, keys, mode, latest_map=latest_map)

    has_sibling_level = mode in (
        PatchGroupingMode.BY_PROJECT,
        PatchGroupingMode.BY_STATUS,
    )
    has_date_subgroups = mode is PatchGroupingMode.BY_DATE
    l0_indices: dict[str, list[int]] = {}
    root_indices: dict[tuple[str, str], list[int]] = {}
    date_subgroup_indices: dict[tuple[str, str], list[int]] = {}
    for i in walk:
        k = keys[i]
        l0_indices.setdefault(k.l0, []).append(i)
        if has_sibling_level and k.sibling_root:
            root_indices.setdefault((k.l0, k.sibling_root), []).append(i)
        if has_date_subgroups and k.date_subgroup:
            date_subgroup_indices.setdefault((k.l0, k.date_subgroup), []).append(i)

    entries: list[PatchTreeEntry] = []
    cur_l0: str | None = None
    cur_l0_collapsed = False
    cur_root: str = ""
    cur_root_collapsed = False
    cur_date_subgroup: str = ""
    cur_date_subgroup_collapsed = False

    for i in walk:
        k = keys[i]
        if cur_l0 is None or k.l0 != cur_l0:
            l0_key: GroupKey = (k.l0,)
            cur_l0_collapsed = registry.is_collapsed(l0_key)
            entries.append(
                PatchTreeEntry(
                    kind="group",
                    group=PatchGroupRow(
                        level=0,
                        group_key=l0_key,
                        patch_indices=tuple(l0_indices[k.l0]),
                        is_collapsed=cur_l0_collapsed,
                    ),
                )
            )
            cur_l0 = k.l0
            cur_root = ""
            cur_root_collapsed = False
            cur_date_subgroup = ""
            cur_date_subgroup_collapsed = False
        if cur_l0_collapsed:
            continue

        if has_date_subgroups and k.date_subgroup:
            if k.date_subgroup != cur_date_subgroup:
                cur_date_subgroup = k.date_subgroup
                date_subgroup_key: GroupKey = (k.l0, k.date_subgroup)
                cur_date_subgroup_collapsed = registry.is_collapsed(date_subgroup_key)
                entries.append(
                    PatchTreeEntry(
                        kind="group",
                        group=PatchGroupRow(
                            level=1,
                            group_key=date_subgroup_key,
                            patch_indices=tuple(
                                date_subgroup_indices[(k.l0, k.date_subgroup)]
                            ),
                            is_collapsed=cur_date_subgroup_collapsed,
                        ),
                    )
                )
        else:
            cur_date_subgroup = ""
            cur_date_subgroup_collapsed = False

        if cur_date_subgroup_collapsed:
            continue

        if has_sibling_level and k.sibling_root:
            siblings = root_indices.get((k.l0, k.sibling_root), [])
            if len(siblings) >= 2 and k.sibling_root != cur_root:
                cur_root = k.sibling_root
                deep_key: GroupKey = (k.l0, k.sibling_root)
                cur_root_collapsed = registry.is_collapsed(deep_key)
                entries.append(
                    PatchTreeEntry(
                        kind="group",
                        group=PatchGroupRow(
                            level=1,
                            group_key=deep_key,
                            patch_indices=tuple(siblings),
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
        entries.append(PatchTreeEntry(kind="patch", patch_idx=i))

    return entries
