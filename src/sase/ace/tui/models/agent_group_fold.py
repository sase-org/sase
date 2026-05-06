"""Per-group fold registry for the Agents-tab grouping tree.

Each group key is an arbitrary-length ``tuple[str, ...]``. Common shapes:

* ``(project,)`` for an L0 project banner;
* ``(project, changespec)`` for an L1 ChangeSpec banner (3-level mode)
  or ``(project, name_root)`` for an L1 name-root banner (2-level
  fallback);
* ``(project, changespec, name_root)`` for an L2 name-root banner in
  3-level mode;
* ``(*parent_key, name_root, name_prefix)`` for dotted-name prefix
  subgroups such as ``("Done", "sase-42", "sase-42.2")``.

This module is a thin compatibility re-export of the neutral
:mod:`sase.ace.tui.models.group_fold` types so existing Agent imports
keep working while the CLs tab consumes the same registry.

This registry layers *above* the existing per-workflow
:class:`FoldStateManager`: workflow-level folds only matter once the
group containing the workflow is expanded.
"""

from __future__ import annotations

from .group_fold import GroupFoldRegistry, GroupKey

# Back-compat alias for the Agents-tab callers that still reference the
# old name.  ``AgentGroupFoldRegistry is GroupFoldRegistry`` so isinstance
# checks and direct construction both keep working.
AgentGroupFoldRegistry = GroupFoldRegistry

__all__ = ["AgentGroupFoldRegistry", "GroupFoldRegistry", "GroupKey"]
