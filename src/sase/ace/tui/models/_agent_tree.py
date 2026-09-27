"""Pure in-memory tree projection for rootless agent clans."""

from __future__ import annotations

from ._agent_tree_anchor import (
    TreeIndex as TreeIndex,
    filter_tree_rows,
    presentation_anchor,
    presentation_anchor_lookup,
    tree_parent_lookup,
)
from ._agent_tree_clan import (
    ClanKey as ClanKey,
    project_clan_tree,
    project_mixed_agent_tree,
)
from ._agent_tree_fold import (
    agent_fold_key,
    agent_gating_fold_key,
    agent_is_tree_child,
    agent_parent_fold_key,
    agent_tree_depth,
    agent_tree_title,
)

__all__ = [
    "agent_fold_key",
    "agent_gating_fold_key",
    "agent_is_tree_child",
    "agent_parent_fold_key",
    "agent_tree_depth",
    "agent_tree_title",
    "filter_tree_rows",
    "presentation_anchor",
    "presentation_anchor_lookup",
    "project_clan_tree",
    "project_mixed_agent_tree",
    "tree_parent_lookup",
]
