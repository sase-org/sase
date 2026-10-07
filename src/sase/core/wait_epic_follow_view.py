"""Shared epic-follow view model and plain-text phrasing.

Projects the persisted ``wait_for_epics_of`` (armed ``%wait(for_epic=)``
targets) and ``wait_epic_follows`` (per-target ``launching`` / ``following``
/ ``blocked`` stages) markers written by the epic-follow release phase into
one Agent-model-agnostic view per target. The TUI wait counts, the satisfied
predicate, and the render cache key read these helpers today; the TUI lanes,
CLI rows, and Telegram status text use the phrasing in later phases so every
surface tells the same story.

Pure in-memory coercion over already-loaded markers: never touches the
filesystem.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# States the release phase persists. ``none`` and ``agent`` are transient
# evaluations and are never stored; coercion drops them.
_PERSISTED_FOLLOW_STATES = ("launching", "following", "blocked")

# Persisted stages that keep a waiter parked. ``following`` parks through
# the ordinary bead-wait machinery instead (the promoted epic beads).
FOLLOW_BLOCKING_STATES = ("launching", "blocked")

_FOLLOWING_STATE = "following"

# Human phrasing for the persisted ``blocked`` reasons emitted by the
# sase-core reducer. Unknown reasons fall back to the raw reason or detail.
_BLOCKED_REASON_PHRASES = {
    "launch_ended_without_epic": "ended without an epic",
    "launch_skipped": "was skipped",
    "target_dismissed_during_launch": "ended when the target was dismissed",
    "cycle": "would wait on the waiter",
}


@dataclass(frozen=True, slots=True)
class EpicFollowView:
    """One wait target's persisted epic-follow stage, in display shape."""

    target: str = ""
    state: str = "none"
    epic_ids: tuple[str, ...] = ()
    added_bead_ids: tuple[str, ...] = ()
    members: tuple[str, ...] = ()
    since: float = 0.0
    reason: str | None = None
    detail: str | None = None
    resume_command: str | None = None
    skipped_epic_ids: tuple[str, ...] = field(default_factory=tuple)


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        item.strip() for item in value if isinstance(item, str) and item.strip()
    )


def _field(source: Mapping[str, Any] | Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _since_value(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _view_from_entry(entry: Mapping[str, Any] | Any) -> EpicFollowView | None:
    """Coerce one raw follow entry; ``None`` when it carries no stage."""
    target = _optional_str(_field(entry, "target"))
    if target is None:
        return None
    raw_state = _field(entry, "state")
    state = (
        raw_state.strip().lower()
        if isinstance(raw_state, str) and raw_state.strip()
        else ""
    )
    if state not in _PERSISTED_FOLLOW_STATES:
        return None
    return EpicFollowView(
        target=target,
        state=state,
        epic_ids=_str_tuple(_field(entry, "epic_ids")),
        added_bead_ids=_str_tuple(_field(entry, "added_bead_ids")),
        members=_str_tuple(_field(entry, "members")),
        since=_since_value(_field(entry, "since")),
        reason=_optional_str(_field(entry, "reason")),
        detail=_optional_str(_field(entry, "detail")),
        resume_command=_optional_str(_field(entry, "resume_command")),
        skipped_epic_ids=_str_tuple(_field(entry, "skipped_epic_ids")),
    )


def _raw_follow_entries(source: Any) -> Iterable[Any]:
    if isinstance(source, Mapping):
        raw = source.get("wait_epic_follows")
        return raw if isinstance(raw, (list, tuple)) else ()
    entries = getattr(source, "wait_epic_follows", None)
    if entries is None:
        if isinstance(source, (list, tuple)):
            return source
        return ()
    return entries if isinstance(entries, (list, tuple)) else ()


def epic_follow_views(source: Any) -> tuple[EpicFollowView, ...]:
    """Return the persisted follow stages for an agent, marker, or entries.

    Accepts a TUI ``Agent`` (or its wait-display source), a
    ``waiting.json``/``agent_meta.json`` mapping, or a bare iterable of raw
    follow entries (wire objects or plain mappings). Entries without a
    target or without a persisted stage are dropped, mirroring the scan-wire
    coercion. Never performs I/O.
    """
    views: list[EpicFollowView] = []
    seen: set[str] = set()
    for entry in _raw_follow_entries(source):
        if isinstance(entry, EpicFollowView):
            view = entry
            if view.state not in _PERSISTED_FOLLOW_STATES:
                continue
        else:
            coerced = _view_from_entry(entry)
            if coerced is None:
                continue
            view = coerced
        if view.target in seen:
            continue
        seen.add(view.target)
        views.append(view)
    return tuple(views)


def _raw_names(source: Any, name: str) -> list[str]:
    if isinstance(source, Mapping):
        raw = source.get(name)
    else:
        raw = getattr(source, name, None)
    if not isinstance(raw, (list, tuple)):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def armed_follow_targets(source: Any) -> list[str]:
    """Return the ordered intersection of ``wait_for_epics_of``/``waiting_for``.

    A marker without the armed-targets field behaves exactly as before the
    feature: no target is armed and nothing follows. Never performs I/O.
    """
    armed = _raw_names(source, "wait_for_epics_of")
    if not armed:
        return []
    allowed = set(_raw_names(source, "waiting_for"))
    return list(dict.fromkeys(item for item in armed if item in allowed))


def authored_wait_beads(source: Any) -> list[str]:
    """Return ``wait_for_beads`` minus beads a follow promotion derived.

    The release phase records only newly appended epics in
    ``added_bead_ids``, so a bead the user also authored is never listed
    there and stays authored. Order and multiplicity are preserved. Never
    performs I/O.
    """
    if isinstance(source, Mapping):
        raw = source.get("wait_for_beads")
        beads = (
            [item for item in raw if isinstance(item, str)]
            if isinstance(raw, list)
            else []
        )
    else:
        raw = getattr(source, "waiting_for_beads", None) or getattr(
            source, "wait_for_beads", None
        )
        beads = list(raw) if isinstance(raw, (list, tuple)) else []
    added: set[str] = set()
    for view in epic_follow_views(source):
        added.update(view.added_bead_ids)
    if not added:
        return [bead for bead in beads if isinstance(bead, str)]
    return [bead for bead in beads if bead not in added]


def epic_follow_state_token(source: Any) -> tuple[Any, ...]:
    """Return a hashable token of the follow state for render cache keys."""
    return (
        tuple(armed_follow_targets(source)),
        tuple(
            (
                view.target,
                view.state,
                view.epic_ids,
                view.added_bead_ids,
                view.members,
                view.since,
                view.reason,
                view.detail,
                view.resume_command,
                view.skipped_epic_ids,
            )
            for view in epic_follow_views(source)
        ),
    )


def describe_epic_follow(view: EpicFollowView) -> str:
    """Return the shared plain-text phrasing for one follow stage.

    The TUI lanes, CLI wait rows, and Telegram status text all use these
    strings so the hand-off reads identically on every surface.
    """
    if view.state == _FOLLOWING_STATE and view.epic_ids:
        if len(view.epic_ids) == 1:
            return f"waits on {view.target}'s epic {view.epic_ids[0]}"
        epics = ", ".join(view.epic_ids)
        return f"waits on {view.target}'s epics {epics}"
    if view.state == _FOLLOWING_STATE:
        return f"waits on {view.target}'s epic launch"
    if view.state == "blocked":
        phrase = _BLOCKED_REASON_PHRASES.get(view.reason or "")
        if phrase is None:
            phrase = view.reason or view.detail or "is blocked"
        text = f"blocked: {view.target}'s epic launch {phrase}"
        if view.resume_command:
            text += f" (resume: {view.resume_command})"
        return text
    return f"waits on {view.target}'s epic launch"


__all__ = [
    "EpicFollowView",
    "FOLLOW_BLOCKING_STATES",
    "armed_follow_targets",
    "authored_wait_beads",
    "describe_epic_follow",
    "epic_follow_state_token",
    "epic_follow_views",
]
