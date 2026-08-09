"""Group/heading tree for the Patches pane.

Models a flat sequence of banner + Patch entries from a list of
Patches.  Mirrors the shape of ``sase.ace.tui.models.agent_groups``
but stays separate so Patch-specific bucketing rules don't leak into the
Agent code (or vice versa).

Modes:

* ``BY_PROJECT`` — L0 project, L1 sibling root only when 2+ Patches share
  the same ``foobar``-style base name.
* ``BY_DATE`` — L0 date bucket from the latest TIMESTAMPS entry;
  ``Today`` / ``Yesterday`` add 1-hour L1 windows, ``This Week`` adds
  day L1 headings, and ``Earlier`` adds week L1 headings plus
  ``(no timestamp)``.
* ``BY_STATUS`` — L0 status bucket from the literal ``status`` string;
  L1 sibling root only when 2+ Patches share the same base name inside the
  same status bucket.

All modes share the generic :class:`~sase.ace.tui.models.group_fold.GroupFoldRegistry`
for collapse/expand state.
"""

from ._buckets import (
    PatchGroupingMode,
    date_bucket_for_patch,
    date_bucket_sort_index,
    date_subgroup_for_patch,
    date_subgroup_sort_key,
    latest_patch_timestamp,
    status_bucket_for_patch,
    status_sort_index,
)
from ._keys import sibling_root_for_patch
from ._tree import (
    PatchGroupRow,
    PatchTreeEntry,
    build_patch_tree,
    enumerate_patch_group_keys,
)

__all__ = [
    "PatchGroupRow",
    "PatchGroupingMode",
    "PatchTreeEntry",
    "build_patch_tree",
    "date_bucket_for_patch",
    "date_bucket_sort_index",
    "date_subgroup_for_patch",
    "date_subgroup_sort_key",
    "enumerate_patch_group_keys",
    "latest_patch_timestamp",
    "sibling_root_for_patch",
    "status_bucket_for_patch",
    "status_sort_index",
]
