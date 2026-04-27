"""Per-group fold registry for the Agents-tab grouping tree.

Each group key is an arbitrary-length ``tuple[str, ...]`` —

* ``(project,)`` for an L0 project banner;
* ``(project, changespec)`` for an L1 ChangeSpec banner (3-level mode)
  or ``(project, name_root)`` for an L1 name-root banner (2-level
  fallback);
* ``(project, changespec, name_root)`` for an L2 name-root banner in
  3-level mode.

Groups default to expanded; only the collapsed set is stored so
first-paint and brand-new groups behave identically.

This registry layers *above* the existing per-workflow
:class:`FoldStateManager`: workflow-level folds only matter once the
group containing the workflow is expanded.

``l``/``h`` step the focused group's state; ``L``/``H`` apply to every
known group at once and remain the single-keystroke escape hatch out of
any per-group state.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

GroupKey = tuple[str, ...]


@dataclass
class AgentGroupFoldRegistry:
    """Tracks which groups are currently collapsed.

    Stores only the *collapsed* set; any key not present is expanded.
    Mutating methods return ``True`` when the registry actually changed
    so callers can short-circuit redundant refreshes.

    ``version`` increments on every successful mutation so caches keyed
    on fold state can invalidate without inspecting the set itself.
    """

    collapsed: set[GroupKey] = field(default_factory=set)
    version: int = 0

    def is_collapsed(self, key: GroupKey) -> bool:
        return key in self.collapsed

    def collapse(self, key: GroupKey) -> bool:
        if key in self.collapsed:
            return False
        self.collapsed.add(key)
        self.version += 1
        return True

    def expand(self, key: GroupKey) -> bool:
        if key not in self.collapsed:
            return False
        self.collapsed.discard(key)
        self.version += 1
        return True

    def collapse_keys(self, keys: Iterable[GroupKey]) -> bool:
        changed = False
        for key in keys:
            if self.collapse(key):
                changed = True
        return changed

    def expand_keys(self, keys: Iterable[GroupKey]) -> bool:
        changed = False
        for key in keys:
            if self.expand(key):
                changed = True
        return changed

    def clear_unknown(self, known: Iterable[GroupKey]) -> None:
        """Drop collapsed-set entries not in *known*.

        Called once per refresh so groups whose last agent disappeared
        don't leave a dangling collapsed entry that re-applies if the
        same key reappears later.
        """
        known_set = set(known)
        before = len(self.collapsed)
        self.collapsed.intersection_update(known_set)
        if len(self.collapsed) != before:
            self.version += 1
