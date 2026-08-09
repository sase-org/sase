"""Generic per-group fold registry, shared by Agents and Patches.

Each group key is an arbitrary-length ``tuple[str, ...]``. Groups default
to expanded; only the collapsed set is stored so first-paint and brand-new
groups behave identically. Keyboard behavior belongs to each caller; this
module only stores independent binary state for the group keys it is given.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

GroupKey = tuple[str, ...]


class GroupFoldView(Protocol):
    """Minimal single-tree fold view consumed by grouping renderers."""

    def is_collapsed(self, key: GroupKey) -> bool: ...


@dataclass
class GroupFoldRegistry:
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

    def snapshot(self) -> frozenset[GroupKey]:
        """Return an immutable copy of the collapsed-key set."""
        return frozenset(self.collapsed)

    def restore(self, collapsed: Iterable[GroupKey]) -> bool:
        """Replace collapse state from an immutable persistence snapshot.

        A changed restore replaces the backing set and advances ``version`` so
        render/navigation caches never mistake restored state for the prior
        session-local registry contents.
        """
        restored = set(collapsed)
        if restored == self.collapsed:
            return False
        self.collapsed = restored
        self.version += 1
        return True

    def clear_unknown(self, known: Iterable[GroupKey]) -> bool:
        """Drop collapsed-set entries not in *known*.

        Called once per refresh so groups whose last member disappeared
        don't leave a dangling collapsed entry that re-applies if the
        same key reappears later.
        """
        known_set = set(known)
        before = len(self.collapsed)
        self.collapsed.intersection_update(known_set)
        if len(self.collapsed) != before:
            self.version += 1
            return True
        return False
