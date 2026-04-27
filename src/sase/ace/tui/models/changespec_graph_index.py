"""Graph index over a ChangeSpec list for ancestors / children / siblings.

Built once whenever ``_all_changespecs`` changes; reused across every
selection so the ancestors / children / siblings panel does not rebuild
its name / children / status maps on every j/k navigation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sase.core.changespec import strip_reverted_suffix

from ...changespec import ChangeSpec, get_base_status

_TERMINAL_STATUSES = ("Reverted", "Archived")
_SUBMITTED_STATUSES = ("Submitted",)
_SIBLING_SUFFIX_RE = re.compile(r"^.+__(\d+)$")


@dataclass
class ChangeSpecGraphIndex:
    """O(1) lookup of relationships across an immutable ChangeSpec list."""

    name_map: dict[str, ChangeSpec] = field(default_factory=dict)
    children_by_parent: dict[str, list[ChangeSpec]] = field(default_factory=dict)
    status_by_name: dict[str, str] = field(default_factory=dict)
    siblings_by_base_name: dict[str, list[ChangeSpec]] = field(default_factory=dict)
    terminal_count: int = 0
    submitted_count: int = 0

    def get_children(self, name: str) -> list[ChangeSpec]:
        return self.children_by_parent.get(name.lower(), [])

    def get_siblings_of(self, changespec: ChangeSpec) -> list[ChangeSpec]:
        base = strip_reverted_suffix(changespec.name).lower()
        family = self.siblings_by_base_name.get(base, [])
        return [cs for cs in family if cs.name.lower() != changespec.name.lower()]

    def get_status(self, name: str) -> str:
        return self.status_by_name.get(name.lower(), "WIP")


def build_changespec_graph_index(
    changespecs: list[ChangeSpec],
) -> ChangeSpecGraphIndex:
    """Build a :class:`ChangeSpecGraphIndex` for ``changespecs``."""
    name_map: dict[str, ChangeSpec] = {}
    children_by_parent: dict[str, list[ChangeSpec]] = {}
    status_by_name: dict[str, str] = {}
    siblings_by_base_name: dict[str, list[ChangeSpec]] = {}
    terminal_count = 0
    submitted_count = 0

    for cs in changespecs:
        key = cs.name.lower()
        name_map[key] = cs
        status_by_name[key] = cs.status

        base_status = get_base_status(cs.status)
        if base_status in _TERMINAL_STATUSES:
            terminal_count += 1
        elif base_status in _SUBMITTED_STATUSES:
            submitted_count += 1

        if cs.parent:
            parent_lower = cs.parent.lower()
            children_by_parent.setdefault(parent_lower, []).append(cs)

        base_name = strip_reverted_suffix(cs.name).lower()
        siblings_by_base_name.setdefault(base_name, []).append(cs)

    for family in siblings_by_base_name.values():
        family.sort(
            key=lambda c: (
                int(m.group(1)) if (m := _SIBLING_SUFFIX_RE.match(c.name)) else 0
            )
        )

    return ChangeSpecGraphIndex(
        name_map=name_map,
        children_by_parent=children_by_parent,
        status_by_name=status_by_name,
        siblings_by_base_name=siblings_by_base_name,
        terminal_count=terminal_count,
        submitted_count=submitted_count,
    )
