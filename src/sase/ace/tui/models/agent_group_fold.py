"""Group-fold state for the Agents-tab two-level grouping tree.

Tracks a single global expansion level layered *above* the existing
per-workflow :class:`FoldStateManager`:

* ``L0`` — only project headers visible.
* ``L1`` — project + name-root headers visible.
* ``L2`` — all banners + agents visible (default).

At ``L2`` the existing per-workflow fold manager continues to govern
attempt visibility.  ``l``/``h`` step this level; ``L``/``H`` jump to
the endpoints (``L2`` and ``L0`` respectively).
"""

from __future__ import annotations

from dataclasses import dataclass

GROUP_LEVEL_MIN = 0
GROUP_LEVEL_MAX = 2


@dataclass
class AgentGroupFoldState:
    """Mutable holder for the global group-fold level."""

    level: int = GROUP_LEVEL_MAX

    def expand(self) -> bool:
        """Advance one level (L0→L1→L2).  Returns ``True`` on change."""
        if self.level < GROUP_LEVEL_MAX:
            self.level += 1
            return True
        return False

    def collapse(self) -> bool:
        """Retreat one level (L2→L1→L0).  Returns ``True`` on change."""
        if self.level > GROUP_LEVEL_MIN:
            self.level -= 1
            return True
        return False

    def expand_all(self) -> bool:
        """Jump to L2 (everything visible).  Returns ``True`` on change."""
        if self.level == GROUP_LEVEL_MAX:
            return False
        self.level = GROUP_LEVEL_MAX
        return True

    def collapse_all(self) -> bool:
        """Jump to L0 (only project banners).  Returns ``True`` on change."""
        if self.level == GROUP_LEVEL_MIN:
            return False
        self.level = GROUP_LEVEL_MIN
        return True
