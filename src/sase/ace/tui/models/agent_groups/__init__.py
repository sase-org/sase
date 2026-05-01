"""Two- or three-level grouping tree for an Agents-tab panel.

Builds a flat sequence of banner + agent entries from a list of agents.
Each panel decides independently between two layouts based on whether
any of its non-project-scoped agents targets a ChangeSpec
(``cl_name != ""``):

* **2-level layout** (no ChangeSpec anywhere in the panel):
    1. **Project** — derived from ``Agent.project_file``.
    2. **Name root** — the part of the agent's name before the first ``.``.

* **3-level layout** (at least one non-project agent has a ChangeSpec):
    1. **Project**
    2. **ChangeSpec** (``Agent.cl_name``); project-scoped agents and
       agents lacking one fall into a synthetic ``"(no ChangeSpec)"``
       bucket sorted last under their project.
    3. **Name root**

Tag-level grouping is not part of this tree — tags drive the dynamic
side panels (see :mod:`sase.ace.tui.models.agent_panels`), so each panel
already represents a single tag bucket.

Workflow children inherit grouping identity from their parent so that
banners are never emitted between a parent and its child steps.

Each group has a binary collapsed/expanded state, tracked per-key in an
:class:`AgentGroupFoldRegistry`.  When a group is collapsed its
descendants are suppressed; sibling groups remain unaffected.

Group ordering is deterministic and independent of the input agent
list's order: named projects sort before ``(no project)``; named
ChangeSpecs sort before the ``(no ChangeSpec)`` bucket; ungrouped
agents (dotless and singleton-name-root) sort first within their
ChangeSpec bucket so they render directly under the ChangeSpec banner,
before any name-root banner.  Within each group, members keep their
original input order via a stable sort.

Name-root banners are only emitted when the name-root group contains
two or more entries; a singleton root renders its lone agent directly
under the parent banner without an extra header.  In ``BY_DATE`` mode,
visible real time-window banners are emitted even for singleton windows.
"""

from ._buckets import (
    NO_CHANGESPEC_LABEL,
    NO_HOUR_LABEL,
    NO_PROJECT,
    GroupingMode,
    _NEEDS_ATTENTION_STATUSES,
    _NEEDS_INPUT_STATUSES,
    _TERMINAL_STATUSES,
    date_bucket_for,
    hour_bucket_for,
    status_bucket_for,
    time_window_bucket_for,
)
from ._keys import grouping_keys_for_agents, panel_uses_changespec_level
from ._tree import (
    GroupRow,
    TreeEntry,
    banner_label,
    banner_summary_text,
    build_agent_tree,
    compute_banner_summary,
    enumerate_group_keys,
    find_visible_ancestor_banner,
)

# Back-compat aliases for legacy imports that referenced the old
# underscore-prefixed names.  Plain assignments (not re-imports) so
# pyvision treats them as module-level attributes rather than imports
# of private symbols.
_date_bucket_for = date_bucket_for
_status_bucket_for = status_bucket_for
_grouping_keys_for_agents = grouping_keys_for_agents
_panel_uses_changespec_level = panel_uses_changespec_level

__all__ = [
    "GroupRow",
    "GroupingMode",
    "NO_CHANGESPEC_LABEL",
    "NO_HOUR_LABEL",
    "NO_PROJECT",
    "TreeEntry",
    "banner_label",
    "banner_summary_text",
    "build_agent_tree",
    "compute_banner_summary",
    "date_bucket_for",
    "enumerate_group_keys",
    "find_visible_ancestor_banner",
    "grouping_keys_for_agents",
    "hour_bucket_for",
    "panel_uses_changespec_level",
    "status_bucket_for",
    "time_window_bucket_for",
]
