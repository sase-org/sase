"""Tree builders, banner row records, and banner-display helpers."""

from ._tree_build import build_agent_tree, rendered_group_keys
from ._tree_keys import enumerate_group_keys
from ._tree_rows import GroupRow, TreeEntry
from ._tree_summary import (
    banner_label,
    banner_label_for_group_key,
    banner_summary_text,
    compute_banner_summary,
    find_visible_ancestor_banner,
)

__all__ = [
    "GroupRow",
    "TreeEntry",
    "banner_label",
    "banner_label_for_group_key",
    "banner_summary_text",
    "build_agent_tree",
    "compute_banner_summary",
    "enumerate_group_keys",
    "find_visible_ancestor_banner",
    "rendered_group_keys",
]
