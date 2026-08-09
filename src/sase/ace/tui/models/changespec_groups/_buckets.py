"""Legacy aliases for patch grouping buckets."""

from ..patch_groups import _buckets as _patch_buckets
from ..patch_groups._buckets import (
    PatchGroupingMode,
    date_bucket_for_patch,
    date_bucket_sort_index,
    date_subgroup_for_patch,
    date_subgroup_sort_key,
    latest_patch_timestamp,
    precompute_latest_timestamps,
    status_bucket_for_patch,
    status_sort_index,
)

ChangeSpecGroupingMode = PatchGroupingMode
_parse_timestamp_value = _patch_buckets._parse_timestamp_value
date_bucket_for_changespec = date_bucket_for_patch
date_subgroup_for_changespec = date_subgroup_for_patch
latest_changespec_timestamp = latest_patch_timestamp
status_bucket_for_changespec = status_bucket_for_patch

__all__ = [
    "ChangeSpecGroupingMode",
    "date_bucket_for_changespec",
    "date_bucket_sort_index",
    "date_subgroup_for_changespec",
    "date_subgroup_sort_key",
    "latest_changespec_timestamp",
    "precompute_latest_timestamps",
    "status_bucket_for_changespec",
    "status_sort_index",
]
