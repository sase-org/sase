"""Per-group fold registry for the Agents-tab two-level grouping tree.

Each group (an L0 project key — a 2-tuple ``(project, cl_name)`` — or an
L1 name-root key — a 3-tuple ``(project, cl_name, name_root)``) tracks a
binary collapsed/expanded state.  Groups default to expanded; only the
collapsed set is stored so first-paint and brand-new groups behave
identically.

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
    """

    collapsed: set[GroupKey] = field(default_factory=set)

    def is_collapsed(self, key: GroupKey) -> bool:
        return key in self.collapsed

    def collapse(self, key: GroupKey) -> bool:
        if key in self.collapsed:
            return False
        self.collapsed.add(key)
        return True

    def expand(self, key: GroupKey) -> bool:
        if key not in self.collapsed:
            return False
        self.collapsed.discard(key)
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
        self.collapsed.intersection_update(known_set)
