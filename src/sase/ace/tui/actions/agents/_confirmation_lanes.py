"""Pure agent-lane projection for kill and dismissal confirmations."""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent


@dataclass(frozen=True, slots=True)
class _AgentConfirmationEntry:
    """One affected agent lane and any exact running family members."""

    lane_name: str
    running_member_names: tuple[str, ...] = ()


@dataclass(slots=True)
class _PendingEntry:
    lane_name: str
    running_member_names: list[str]


def confirmation_lane_entries(
    targets: Sequence[Agent],
    loaded_agents: Sequence[Agent],
    *,
    include_running_family_members: bool = False,
) -> tuple[_AgentConfirmationEntry, ...]:
    """Project concrete cleanup targets into ordered agent-lane entries.

    Workflow descendants resolve to their workflow lane. Sequential-family
    descendants resolve to the family reference, including families nested
    directly inside a clan. Clan containers are not lanes: a descendant stops
    at the direct member immediately below its clan container.

    Missing parents and compatibility rows degrade to the best identity
    already carried by the concrete row. Repeated concrete targets and
    cascaded descendants are de-duplicated without mutating *targets*.
    """
    rows = _loaded_tree_rows(loaded_agents, targets)
    parent_lookup = _parent_lookup(rows)
    entries: list[_PendingEntry] = []
    entry_indexes: dict[Hashable, int] = {}

    for target in targets:
        owner = _lane_owner(target, parent_lookup)
        family_name = _sequential_family_name(owner) or _sequential_family_name(target)
        lane_name = _lane_name(owner, target, family_name)
        lane_key = _lane_key(owner, target, family_name, lane_name)

        entry_index = entry_indexes.get(lane_key)
        if entry_index is None:
            entry_index = len(entries)
            entry_indexes[lane_key] = entry_index
            entries.append(_PendingEntry(lane_name, []))

        if not include_running_family_members:
            continue
        if getattr(target, "pid", None) is None:
            continue
        if _sequential_family_name(target) is None:
            continue
        member_name = _presented_concrete_name(target, lane_name)
        if (
            member_name
            and member_name != lane_name
            and member_name not in entries[entry_index].running_member_names
        ):
            entries[entry_index].running_member_names.append(member_name)

    return tuple(
        _AgentConfirmationEntry(
            lane_name=entry.lane_name,
            running_member_names=tuple(entry.running_member_names),
        )
        for entry in entries
    )


def format_confirmation_entries(
    entries: Iterable[_AgentConfirmationEntry],
) -> list[str]:
    """Format lane entries for the shared confirmation-dialog subject parser."""
    lines: list[str] = []
    for entry in entries:
        line = f"  {entry.lane_name}"
        if entry.running_member_names:
            line += " " + ", ".join(
                f"@{member_name}" for member_name in entry.running_member_names
            )
        lines.append(line)
    return lines


def _loaded_tree_rows(
    loaded_agents: Sequence[Agent],
    targets: Sequence[Agent],
) -> tuple[Agent, ...]:
    """Return each already-loaded row once, including attached child lists."""
    rows: list[Agent] = []
    seen: set[int] = set()

    def visit(row: Agent) -> None:
        row_id = id(row)
        if row_id in seen:
            return
        seen.add(row_id)
        rows.append(row)
        for attr in ("runtime_children", "followup_agents"):
            children = getattr(row, attr, ())
            if children:
                for child in children:
                    visit(child)

    for row in (*loaded_agents, *targets):
        visit(row)
    return tuple(rows)


def _parent_lookup(rows: Sequence[Agent]) -> dict[str, Agent]:
    """Build the subset of the Agents-tree parent index needed here."""
    lookup: dict[str, Agent] = {}
    for row in rows:
        if getattr(row, "is_clan_container", False):
            try:
                from ...models._agent_tree import agent_fold_key

                fold_key = agent_fold_key(row)
            except (AttributeError, TypeError):
                fold_key = None
            if fold_key:
                lookup[fold_key] = row

        raw_suffix = getattr(row, "raw_suffix", None)
        if not raw_suffix:
            continue
        existing = lookup.get(raw_suffix)
        if existing is None or (_is_child_row(existing) and not _is_child_row(row)):
            # Legacy workflow children can repeat their parent's raw suffix.
            lookup[raw_suffix] = row
    return lookup


def _lane_owner(target: Agent, parent_lookup: dict[str, Agent]) -> Agent:
    """Return the workflow/family/standalone row that owns *target*'s lane."""
    current = target
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        parent_key = getattr(current, "tree_parent_key", None)
        if not parent_key and _is_child_row(current):
            parent_key = getattr(current, "parent_timestamp", None)
        if not parent_key:
            return current
        parent = parent_lookup.get(parent_key)
        if parent is None:
            return current
        if getattr(parent, "is_clan_container", False):
            return current
        current = parent
    return current


def _is_child_row(agent: Agent) -> bool:
    try:
        return bool(agent.is_child_row)
    except AttributeError:
        return bool(
            getattr(agent, "parent_workflow", None)
            or getattr(agent, "parent_timestamp", None)
        )


def _sequential_family_name(agent: Agent) -> str | None:
    """Return a model-derived family reference for a serial family row."""
    if getattr(agent, "agent_family_parallel", False):
        return None
    family = getattr(agent, "agent_family", None)
    if family:
        return str(family)

    # Family-name inference is intentionally gated by structural metadata.
    # Arbitrary workflow step names may resemble legacy family suffixes (for
    # example ``step.2``) but remain part of their owning workflow lane.
    is_family_root = bool(
        getattr(agent, "plan_chain_root", False)
        or getattr(agent, "agent_family_role", None) == "root"
    )
    is_family_child = bool(
        getattr(agent, "parent_timestamp", None)
        and not getattr(agent, "parent_workflow", None)
        and (
            getattr(agent, "role_suffix", None)
            or getattr(agent, "agent_family_role", None)
        )
    )
    if not is_family_root and not is_family_child:
        return None
    try:
        from ...models._agent_status_family import agent_family_name

        return agent_family_name(agent)
    except (AttributeError, TypeError):
        return None


def _lane_name(
    owner: Agent,
    target: Agent,
    family_name: str | None,
) -> str:
    if family_name:
        for row in (owner, target):
            presenter = getattr(row, "presented_family_reference_name", None)
            if callable(presenter):
                try:
                    presented = presenter()
                except (AttributeError, TypeError):
                    presented = None
                if presented:
                    return str(presented)
        return family_name

    for row in (owner, target):
        for attr in ("presented_agent_name", "agent_name"):
            value = getattr(row, attr, None)
            if value:
                return str(value)
        try:
            display_name = getattr(row, "display_name", None)
        except (AttributeError, TypeError):
            display_name = None
        if display_name:
            return str(display_name)
        for attr in ("workflow", "step_name", "cl_name"):
            value = getattr(row, attr, None)
            if value:
                return str(value)
    return "unnamed agent"


def _lane_key(
    owner: Agent,
    target: Agent,
    family_name: str | None,
    lane_name: str,
) -> Hashable:
    if family_name:
        return (
            "family",
            family_name,
            getattr(owner, "agent_clan_generation", None)
            or getattr(target, "agent_clan_generation", None),
        )
    for row in (owner, target):
        try:
            identity = getattr(row, "identity", None)
            hash(identity)
        except (AttributeError, TypeError):
            continue
        if identity is not None:
            return ("agent", identity)
    return ("fallback", lane_name, id(owner))


def _presented_concrete_name(agent: Agent, lane_name: str) -> str | None:
    presented_identity = getattr(agent, "presented_identity_name", None)
    if presented_identity:
        return str(presented_identity)

    presented_name = getattr(agent, "presented_agent_name", None)
    raw_name = getattr(agent, "agent_name", None)
    if presented_name and (presented_name != lane_name or not raw_name):
        return str(presented_name)
    if raw_name:
        return str(raw_name)
    return str(presented_name) if presented_name else None


__all__ = [
    "confirmation_lane_entries",
    "format_confirmation_entries",
]
