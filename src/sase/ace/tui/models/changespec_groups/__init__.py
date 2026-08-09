"""Legacy aliases for patch grouping models."""

from typing import Any

from ..patch_groups import (
    PatchGroupingMode,
    PatchGroupRow,
    PatchTreeEntry,
    build_patch_tree,
    date_bucket_for_patch,
    date_bucket_sort_index,
    date_subgroup_for_patch,
    date_subgroup_sort_key,
    latest_patch_timestamp,
    sibling_root_for_patch,
    status_bucket_for_patch,
    status_sort_index,
)
from ..patch_groups import _buckets as _patch_buckets
from . import _buckets as _legacy_buckets
from ._tree import (
    enumerate_changespec_group_keys as _tree_enumerate_changespec_group_keys,  # legacy compatibility alias
)

ChangeSpecGroupingMode = PatchGroupingMode  # legacy compatibility alias
ChangeSpecGroupRow = PatchGroupRow  # legacy compatibility alias
ChangeSpecTreeEntry = PatchTreeEntry  # legacy compatibility alias
date_bucket_for_changespec = date_bucket_for_patch  # legacy compatibility alias
date_subgroup_for_changespec = date_subgroup_for_patch  # legacy compatibility alias
latest_changespec_timestamp = latest_patch_timestamp  # legacy compatibility alias
sibling_root_for_changespec = sibling_root_for_patch  # legacy compatibility alias
status_bucket_for_changespec = status_bucket_for_patch  # legacy compatibility alias


def _sync_legacy_bucket_monkeypatch() -> None:
    _patch_buckets.parse_timestamp_value = _legacy_buckets._parse_timestamp_value


# legacy compatibility alias
def _build_changespec_tree(
    *args: Any, **kwargs: Any
) -> list[PatchTreeEntry]:  # legacy compatibility alias
    _sync_legacy_bucket_monkeypatch()
    entries = build_patch_tree(*args, **kwargs)
    return [
        PatchTreeEntry(
            # legacy compatibility alias
            kind="changespec",
            group=entry.group,
            patch_idx=entry.patch_idx,
        )  # legacy compatibility alias
        if entry.kind == "patch"
        else entry
        for entry in entries
    ]


def _enumerate_changespec_group_keys(  # legacy compatibility alias
    *args: Any, **kwargs: Any
) -> list[tuple[str, ...]]:
    _sync_legacy_bucket_monkeypatch()
    return _tree_enumerate_changespec_group_keys(
        *args, **kwargs
    )  # legacy compatibility alias


build_changespec_tree = _build_changespec_tree  # legacy compatibility alias
enumerate_changespec_group_keys = (
    _enumerate_changespec_group_keys  # legacy compatibility alias
)

__all__ = [
    "ChangeSpecGroupingMode",  # legacy compatibility alias
    "ChangeSpecGroupRow",  # legacy compatibility alias
    "ChangeSpecTreeEntry",  # legacy compatibility alias
    "build_changespec_tree",  # legacy compatibility alias
    "date_bucket_for_changespec",  # legacy compatibility alias
    "date_bucket_sort_index",
    "date_subgroup_for_changespec",  # legacy compatibility alias
    "date_subgroup_sort_key",
    "enumerate_changespec_group_keys",  # legacy compatibility alias
    "latest_changespec_timestamp",  # legacy compatibility alias
    "sibling_root_for_changespec",  # legacy compatibility alias
    "status_bucket_for_changespec",  # legacy compatibility alias
    "status_sort_index",
]
