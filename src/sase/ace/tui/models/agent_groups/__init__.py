"""Grouping tree for an Agents-tab panel.

Builds a flat sequence of banner + agent entries from a list of agents.
Each panel decides independently between two layouts based on whether
any of its non-project-scoped agents targets a Patch
(``cl_name != ""``):

* **2-level layout** (no Patch anywhere in the panel):
    1. **Project** — derived from ``Agent.project_file``.
    2. **Name root** — the part of the agent's name before the first ``.``.
       When at least two agents under that root share the first two dotted
       name segments, an optional child **name prefix** subgroup is emitted.
       An exact two-segment parent marker such as ``foo.bar`` participates
       in the same prefix subgroup as descendants such as ``foo.bar.1``.

* **3-level layout** (at least one non-project agent has a Patch):
    1. **Project**
    2. **Patch** (``Agent.cl_name``); project-scoped agents and
       agents lacking one fall into a synthetic ``"(no Patch)"``
       bucket sorted last under their project.
    3. **Name root**
       May contain optional child **name prefix** subgroups, producing a
       fourth structural level.

``BY_STATUS`` replaces the project level with a priority-ordered status
bucket, then uses the same name-root and optional name-prefix levels. Within a
status bucket, standalone lanes render before visible name-root subgroups;
launch recency sorts units only within those two partitions. The same rule
places lanes directly under a name-root before its visible dotted-prefix
subgroups. Subgroups use their outer/root agent's ``start_time`` and remain
contiguous. ``BY_DATE`` replaces the tree with date bucket → time subgroup and
intentionally suppresses name-root/name-prefix grouping.

Tribe-level grouping is not part of this tree — tribes drive the dynamic
side panels (see :mod:`sase.ace.tui.models.agent_panels`), so each panel
already represents a single tribe bucket.

Structural descendants inherit grouping identity from their outer rendered
root so banners are never emitted inside a clan or agent-family subtree.

Each group has a binary collapsed/expanded state, tracked per-key in an
:class:`AgentGroupFoldRegistry`.  When a group is collapsed its
descendants are suppressed; sibling groups remain unaffected.

Group ordering is deterministic and independent of the input agent
list's order: named projects sort before ``(no project)``; named
Patches sort before the ``(no Patch)`` bucket; ungrouped
agents (dotless and singleton-name-root) sort first within their
Patch bucket so they render directly under the Patch banner,
before any name-root banner. Under ``BY_STATUS``, launch recency cannot
interleave that standalone partition with visible subgroups. Within each
group, members keep their original projected parent/child preorder, and each
rooted subtree is sorted as one atomic cluster.

Name-root and name-prefix banners are only emitted when the group
contains two or more entries; singleton groups render their agents
directly under the parent/root banner without an extra header.  In
``BY_DATE`` mode, the L1 subgroup banner uses 1-hour windows under
Today/Yesterday, calendar days under This Week, and Monday-start weeks
under Earlier; real labels always emit a banner, while the synthetic
``(no time)`` label only emits when 2+ agents share it.
"""

from ._buckets import (
    NO_PATCH_LABEL,
    NO_HOUR_LABEL,
    NO_PROJECT,
    GroupingMode,
    _NEEDS_INPUT_STATUSES,
    _STOPPED_STATUSES,
    _TERMINAL_STATUSES,
    date_bucket_for,
    date_subgroup_bucket_for,
    status_bucket_for,
)
from ._keys import (
    grouping_keys_for_agents,
    panel_uses_patch_level,
    status_grouping_signature,
)
from ._tree import (
    GroupRow,
    TreeEntry,
    banner_label,
    banner_label_for_group_key,
    banner_summary_text,
    build_agent_tree,
    compute_banner_summary,
    enumerate_group_keys,
    find_visible_ancestor_banner,
)

NO_CHANGESPEC_LABEL = NO_PATCH_LABEL  # legacy compatibility alias

# Back-compat aliases for legacy imports that referenced the old
# underscore-prefixed names.  Plain assignments (not re-imports) so
# symvision treats them as module-level attributes rather than imports
# of private symbols.
_date_bucket_for = date_bucket_for
_status_bucket_for = status_bucket_for
_grouping_keys_for_agents = grouping_keys_for_agents
_panel_uses_patch_level = panel_uses_patch_level
_panel_uses_changespec_level = panel_uses_patch_level  # legacy compatibility alias

__all__ = [
    "GroupRow",
    "GroupingMode",
    "NO_PATCH_LABEL",
    "NO_CHANGESPEC_LABEL",  # legacy compatibility alias
    "NO_HOUR_LABEL",
    "NO_PROJECT",
    "TreeEntry",
    "banner_label",
    "banner_label_for_group_key",
    "banner_summary_text",
    "build_agent_tree",
    "compute_banner_summary",
    "date_bucket_for",
    "date_subgroup_bucket_for",
    "enumerate_group_keys",
    "find_visible_ancestor_banner",
    "grouping_keys_for_agents",
    "panel_uses_patch_level",
    "status_bucket_for",
    "status_grouping_signature",
]
