"""Legacy aliases for patch grouping trees."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.core.time import local_now

from ..group_fold import GroupKey
from ..patch_groups._buckets import PatchGroupingMode, precompute_latest_timestamps
from ..patch_groups._keys import keys_for_patches, walk_order
from ..patch_groups._tree import (
    PatchGroupRow,
    PatchTreeEntry,
    build_patch_tree,
)

ChangeSpecGroupRow = PatchGroupRow  # legacy compatibility alias
ChangeSpecTreeEntry = PatchTreeEntry  # legacy compatibility alias
build_changespec_tree = build_patch_tree  # legacy compatibility alias
keys_for_changespecs = keys_for_patches  # legacy compatibility alias


def enumerate_changespec_group_keys(  # legacy compatibility alias
    patches: list[Any],
    mode: PatchGroupingMode = PatchGroupingMode.BY_PROJECT,
    now: datetime | None = None,
) -> list[GroupKey]:
    if not patches:
        return []
    reference = now if now is not None else local_now()
    latest_map = (
        precompute_latest_timestamps(patches)
        if mode is PatchGroupingMode.BY_DATE
        else None
    )
    # legacy compatibility alias
    keys = keys_for_changespecs(
        patches, mode, reference, latest_map=latest_map
    )  # legacy compatibility alias
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


__all__ = [
    "ChangeSpecGroupRow",  # legacy compatibility alias
    "ChangeSpecTreeEntry",  # legacy compatibility alias
    "build_changespec_tree",  # legacy compatibility alias
    "enumerate_changespec_group_keys",  # legacy compatibility alias
    "keys_for_changespecs",  # legacy compatibility alias
    "local_now",
]
