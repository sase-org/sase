"""Created-epic and epic-follow wire dataclasses for the agent scan facade.

Split out of :mod:`sase.core.agent_scan_wire_markers` to keep each module
under the 500-line cap. Covers the ``agent_meta.json`` ``created_epics``
record, the effective ``wait_for_epics_of`` armed targets, and the
persisted ``wait_epic_follows`` stages. The per-file marker projections
that carry these fields live in
:mod:`sase.core.agent_scan_wire_markers`; import that module for the
stable import path.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CreatedEpicWire:
    """One entry of ``agent_meta.json``'s ``created_epics`` record.

    Authoritative run → epic entry written by ``sase bead work`` when it
    materializes an epic-tier plan bead on the run's behalf. ``via`` is
    ``host_launch`` or ``agent_command``.
    """

    bead_id: str = ""
    project: str | None = None
    plan_ref: str | None = None
    created_at: str | None = None
    via: str | None = None


def _created_epic_str(value: object) -> str | None:
    """Return *value* as a stripped string, or None when not usable."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def wait_for_epics_of_from_value(value: object) -> list[str]:
    """Coerce a raw ``wait_for_epics_of`` value leniently; never raises."""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
    return result


@dataclass(frozen=True)
class WaitEpicFollowEntryWire:
    """One persisted ``wait_epic_follows`` stage entry.

    Written by the epic-follow release phase when an armed
    ``%wait(for_epic=)`` target reaches ``launching``, ``following``, or
    ``blocked``. ``added_bead_ids`` holds only the epic ids this promotion
    appended to ``wait_for_beads`` for that target.
    """

    target: str = ""
    state: str = "none"
    epic_ids: list[str] = field(default_factory=list)
    added_bead_ids: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)
    since: float = 0.0
    reason: str | None = None
    detail: str | None = None
    resume_command: str | None = None
    skipped_epic_ids: list[str] = field(default_factory=list)


def _follow_entry_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _follow_entry_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _follow_entry_since(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def wait_epic_follows_from_value(value: object) -> list[WaitEpicFollowEntryWire]:
    """Coerce a raw ``wait_epic_follows`` value leniently; never raises.

    Entries without a target or without a persisted stage state
    (``launching`` / ``following`` / ``blocked``) are dropped and unknown
    keys are ignored, mirroring the Rust scanner's coercion.
    """
    if not isinstance(value, list):
        return []
    entries: list[WaitEpicFollowEntryWire] = []
    for item in value:
        if isinstance(item, WaitEpicFollowEntryWire):
            if item.target.strip() and item.state.strip().lower() in (
                "launching",
                "following",
                "blocked",
            ):
                entries.append(item)
            continue
        if not isinstance(item, dict):
            continue
        target = _follow_entry_optional_str(item.get("target"))
        if target is None:
            continue
        raw_state = item.get("state")
        state = (
            raw_state.strip().lower()
            if isinstance(raw_state, str) and raw_state.strip()
            else ""
        )
        if state not in ("launching", "following", "blocked"):
            continue
        entries.append(
            WaitEpicFollowEntryWire(
                target=target,
                state=state,
                epic_ids=_follow_entry_str_list(item.get("epic_ids")),
                added_bead_ids=_follow_entry_str_list(item.get("added_bead_ids")),
                members=_follow_entry_str_list(item.get("members")),
                since=_follow_entry_since(item.get("since")),
                reason=_follow_entry_optional_str(item.get("reason")),
                detail=_follow_entry_optional_str(item.get("detail")),
                resume_command=_follow_entry_optional_str(item.get("resume_command")),
                skipped_epic_ids=_follow_entry_str_list(item.get("skipped_epic_ids")),
            )
        )
    return entries


def created_epics_from_value(value: object) -> list[CreatedEpicWire]:
    """Coerce a raw ``created_epics`` value leniently; never raises.

    Entries without a string ``bead_id`` are dropped and unknown keys are
    ignored, mirroring the Rust scanner's coercion.
    """
    if not isinstance(value, list):
        return []
    entries: list[CreatedEpicWire] = []
    for item in value:
        if isinstance(item, str):
            bead_id = _created_epic_str(item)
            if bead_id is not None:
                entries.append(CreatedEpicWire(bead_id=bead_id))
            continue
        if isinstance(item, CreatedEpicWire):
            if _created_epic_str(item.bead_id) is not None:
                entries.append(item)
            continue
        if not isinstance(item, dict):
            continue
        bead_id = _created_epic_str(item.get("bead_id"))
        if bead_id is None:
            continue
        entries.append(
            CreatedEpicWire(
                bead_id=bead_id,
                project=_created_epic_str(item.get("project")),
                plan_ref=_created_epic_str(item.get("plan_ref")),
                created_at=_created_epic_str(item.get("created_at")),
                via=_created_epic_str(item.get("via")),
            )
        )
    return entries


__all__ = [
    "CreatedEpicWire",
    "WaitEpicFollowEntryWire",
    "created_epics_from_value",
    "wait_epic_follows_from_value",
    "wait_for_epics_of_from_value",
]
