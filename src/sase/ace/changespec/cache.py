"""Legacy cache module backed by :mod:`sase.ace.patch.cache`."""

import sys as _sys

from sase.ace.patch import cache as _cache_module

ChangeSpecSnapshotCache = _cache_module.ChangeSpecSnapshotCache
PatchSnapshotCache = _cache_module.PatchSnapshotCache
find_all_changespecs_cached = _cache_module.find_all_changespecs_cached
find_all_patches_cached = _cache_module.find_all_patches_cached
get_global_snapshot_cache = _cache_module.get_global_snapshot_cache
parse_project_file = _cache_module.parse_project_file

__all__ = [
    "ChangeSpecSnapshotCache",
    "PatchSnapshotCache",
    "find_all_changespecs_cached",
    "find_all_patches_cached",
    "get_global_snapshot_cache",
    "parse_project_file",
]

_sys.modules[__name__] = _cache_module
