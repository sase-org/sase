"""Legacy aliases for patch grouping buckets."""

from ..patch_groups._buckets import (
    PatchGroupingMode,
    date_bucket_for_patch,
    date_bucket_sort_index,
    date_subgroup_for_patch,
    date_subgroup_sort_key,
    latest_patch_timestamp,
    parse_timestamp_value,
    precompute_latest_timestamps,
    status_bucket_for_patch,
    status_sort_index,
)

ChangeSpecGroupingMode = PatchGroupingMode  # legacy compatibility alias
_parse_timestamp_value = parse_timestamp_value
date_bucket_for_changespec = date_bucket_for_patch  # legacy compatibility alias
date_subgroup_for_changespec = date_subgroup_for_patch  # legacy compatibility alias
latest_changespec_timestamp = latest_patch_timestamp  # legacy compatibility alias
status_bucket_for_changespec = status_bucket_for_patch  # legacy compatibility alias

__all__ = [
    "ChangeSpecGroupingMode",  # legacy compatibility alias
    "date_bucket_for_changespec",  # legacy compatibility alias
    "date_bucket_sort_index",
    "date_subgroup_for_changespec",  # legacy compatibility alias
    "date_subgroup_sort_key",
    "latest_changespec_timestamp",  # legacy compatibility alias
    "precompute_latest_timestamps",
    "status_bucket_for_changespec",  # legacy compatibility alias
    "status_sort_index",
]
