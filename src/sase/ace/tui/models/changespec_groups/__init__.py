"""Group/heading tree for the CLs tab.

Models a flat sequence of banner + ChangeSpec entries from a list of
ChangeSpecs.  Mirrors the shape of ``sase.ace.tui.models.agent_groups``
but stays separate so CL-specific bucketing rules don't leak into the
Agent code (or vice versa).

Modes:

* ``BY_PROJECT`` — L0 project, L1 sibling root only when 2+ CLs share
  the same ``foobar``-style base name.
* ``BY_DATE`` — L0 date bucket from the latest TIMESTAMPS entry;
  ``Yesterday`` adds 4-hour L1 windows, ``This Week`` adds day L1
  headings, and ``Earlier`` adds week L1 headings plus ``(no timestamp)``.
* ``BY_STATUS`` — L0 status bucket from the literal ``status`` string;
  L1 sibling root only when 2+ CLs share the same base name inside the
  same status bucket.

All modes share the generic :class:`~sase.ace.tui.models.group_fold.GroupFoldRegistry`
for collapse/expand state.
"""

from ._buckets import (
    ChangeSpecGroupingMode,
    date_bucket_for_changespec,
    date_bucket_sort_index,
    date_subgroup_for_changespec,
    date_subgroup_sort_key,
    latest_changespec_timestamp,
    status_bucket_for_changespec,
    status_sort_index,
)
from ._keys import sibling_root_for_changespec
from ._tree import (
    ChangeSpecGroupRow,
    ChangeSpecTreeEntry,
    build_changespec_tree,
    enumerate_changespec_group_keys,
)

__all__ = [
    "ChangeSpecGroupRow",
    "ChangeSpecGroupingMode",
    "ChangeSpecTreeEntry",
    "build_changespec_tree",
    "date_bucket_for_changespec",
    "date_bucket_sort_index",
    "date_subgroup_for_changespec",
    "date_subgroup_sort_key",
    "enumerate_changespec_group_keys",
    "latest_changespec_timestamp",
    "sibling_root_for_changespec",
    "status_bucket_for_changespec",
    "status_sort_index",
]
