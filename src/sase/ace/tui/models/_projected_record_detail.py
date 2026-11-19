"""Bounded selected-detail ownership for projected artifact-index records."""

from __future__ import annotations

from collections import OrderedDict
import threading
from typing import TYPE_CHECKING, Any
import weakref

if TYPE_CHECKING:
    from .agent import Agent

_HYDRATION_ATTEMPTED_ATTR = "_projected_record_hydration_attempted"
_HYDRATION_PENDING_ATTR = "_projected_record_hydration_pending"
_PROJECTED_DETAIL_STASH_ATTR = "_projected_detail_stash"

#: How many hydrated roster agents the detail owner retains. The current
#: selection plus the most recent previous one: toggling between two rows
#: reuses retained detail instead of re-reading the full record, while
#: everything older falls back to the compact list facts. Roster
#: replacement drops whole Agent objects, so the owner holds only weak
#: references and orphaned entries vanish on the next note.
_DETAIL_OWNER_BOUND = 2

_UNSET = object()

_detail_owner: OrderedDict[int, weakref.ref[Any]] = OrderedDict()
# RLock: eviction inside ``note_projected_detail_retained`` re-enters
# through :func:`_release_projected_agent_detail`.
_detail_owner_lock = threading.RLock()


def projected_agent_needs_hydration(agent: Agent) -> bool:
    """Return True when *agent* is a list-shaped index record needing hydration."""

    return projected_agent_waiting_for_hydration(agent) and not bool(
        getattr(agent, _HYDRATION_PENDING_ATTR, False)
    )


def projected_agent_waiting_for_hydration(agent: Agent) -> bool:
    """Return True while detail rendering should wait for full-record hydration."""

    return (
        agent.record_shape == "list"
        and bool(agent.index_record_dir)
        and not bool(getattr(agent, _HYDRATION_ATTEMPTED_ATTR, False))
    )


def mark_projected_agent_hydration_pending(agent: Agent, pending: bool) -> None:
    """Mark an agent's projected-record hydration worker state."""

    setattr(agent, _HYDRATION_PENDING_ATTR, bool(pending))


def mark_projected_agent_hydration_attempted(agent: Agent) -> None:
    """Prevent repeated synchronous fallbacks after one failed hydration."""

    setattr(agent, _HYDRATION_ATTEMPTED_ATTR, True)


def _detail_value_unchanged(old: Any, new: Any) -> bool:
    """Return whether a hydration write left no observable change."""

    if old is new:
        return True
    try:
        return bool(old == new)
    except Exception:
        return False


def stash_applied_detail(agent: Agent, pre: dict[str, Any]) -> None:
    """Record the pre-hydration values of every field hydration wrote.

    The stash maps each written field to ``(before, hydrated)`` so
    :func:`_release_projected_agent_detail` can restore the compact list
    facts later. Fields hydration rewrote with an equal value are included;
    restoring an equal value is still a release of the hydrated object
    graph.
    """

    post = vars(agent)
    stash: dict[str, tuple[Any, Any]] = {}
    for key, new in post.items():
        if key == _PROJECTED_DETAIL_STASH_ATTR:
            continue
        old = pre.get(key, _UNSET)
        if old is _UNSET or not _detail_value_unchanged(old, new):
            stash[key] = (old, new)
    for key, old in pre.items():
        if key not in post and key != _PROJECTED_DETAIL_STASH_ATTR:
            stash[key] = (old, _UNSET)
    setattr(agent, _PROJECTED_DETAIL_STASH_ATTR, stash)


def projected_agent_compact_copy_value(
    agent: Agent, field_name: str
) -> tuple[bool, Any]:
    """Return one field's compact value for a roster copy.

    A copy made while detail is hydrated starts from the saved compact fact
    when the field still contains the hydrated value. Later optimistic edits
    win, matching detail release semantics. The boolean is false only when
    hydration introduced a field that the compact row did not have.
    """
    current = vars(agent).get(field_name, _UNSET)
    stash = getattr(agent, _PROJECTED_DETAIL_STASH_ATTR, None)
    if not isinstance(stash, dict) or field_name not in stash:
        return (current is not _UNSET, current)
    old, hydrated = stash[field_name]
    if current is not hydrated and not _detail_value_unchanged(current, hydrated):
        return (current is not _UNSET, current)
    return (old is not _UNSET, old)


def prepare_projected_agent_copy(original: Agent, clone: Agent) -> None:
    """Strip unmanaged selected detail from a shallow roster copy."""
    stash = getattr(original, _PROJECTED_DETAIL_STASH_ATTR, None)
    if isinstance(stash, dict):
        for field_name in stash:
            present, value = projected_agent_compact_copy_value(original, field_name)
            if present:
                setattr(clone, field_name, value)
            else:
                try:
                    delattr(clone, field_name)
                except AttributeError:
                    pass
    for attr in (
        _PROJECTED_DETAIL_STASH_ATTR,
        _HYDRATION_ATTEMPTED_ATTR,
        _HYDRATION_PENDING_ATTR,
    ):
        try:
            delattr(clone, attr)
        except AttributeError:
            pass


def note_projected_detail_retained(agent: Agent) -> None:
    """Register a hydrated agent with the bounded detail owner.

    Evicts the oldest retained generation beyond the bound, restoring its
    compact list facts first. Dead references (roster replacement drops
    whole Agent objects) are pruned here so orphaned generations stay
    collectible and are never restored.
    """

    generation = id(agent)
    with _detail_owner_lock:
        _detail_owner[generation] = weakref.ref(agent)
        _detail_owner.move_to_end(generation)
        for known, known_ref in list(_detail_owner.items()):
            if known_ref() is None:
                del _detail_owner[known]
        while len(_detail_owner) > _DETAIL_OWNER_BOUND:
            _oldest, oldest_ref = _detail_owner.popitem(last=False)
            oldest = oldest_ref()
            if oldest is not None:
                _release_projected_agent_detail(oldest)


def _release_projected_agent_detail(agent: Agent) -> bool:
    """Release a hydrated agent's deferred detail back to list facts.

    Restores the pre-hydration values stashed by
    :func:`hydrate_projected_agent`, resets the record shape so detail can
    re-hydrate on the next selection, and drops the owner's registration.
    A field changed after hydration (liveness stamps, optimistic edits)
    keeps its newer value: only fields still holding the hydrated value
    are restored. Returns True when any roster state changed.
    """

    stash = getattr(agent, _PROJECTED_DETAIL_STASH_ATTR, None)
    changed = False
    if stash:
        current_vars = vars(agent)
        for key, (old, hydrated) in stash.items():
            current = current_vars.get(key, _UNSET)
            if current is _UNSET:
                continue
            if current is not hydrated and not _detail_value_unchanged(
                current, hydrated
            ):
                continue
            if old is _UNSET:
                try:
                    delattr(agent, key)
                except AttributeError:
                    pass
                else:
                    changed = True
            elif not _detail_value_unchanged(current, old):
                setattr(agent, key, old)
                changed = True
        setattr(agent, _PROJECTED_DETAIL_STASH_ATTR, {})
    if agent.record_shape != "list":
        agent.record_shape = "list"
        changed = True
    if getattr(agent, _HYDRATION_ATTEMPTED_ATTR, False):
        try:
            delattr(agent, _HYDRATION_ATTEMPTED_ATTR)
        except AttributeError:
            pass
        else:
            changed = True
    with _detail_owner_lock:
        # Only drop the registration when it still points at this agent:
        # a newer generation under a reused identity keeps its entry.
        generation = id(agent)
        known = _detail_owner.get(generation)
        if known is None or known() is None or known() is agent:
            _detail_owner.pop(generation, None)
    return changed
