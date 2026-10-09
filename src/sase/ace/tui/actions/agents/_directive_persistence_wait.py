"""Wait-token patch builders for worker-safe directive persistence."""

from __future__ import annotations

from sase.macro._directive_time import parse_absolute_time, parse_duration

from ._directive_persistence_models import (
    AgentMetaPatch,
    WaitingMarkerPatch,
)


def wait_meta_patch_for_token(
    *,
    wait_names: tuple[str, ...] = (),
    wait_for_epics_of: tuple[str, ...] = (),
    wait_beads: tuple[str, ...] = (),
    wait_hoods: tuple[str, ...] = (),
    time_token: str | None = None,
    update_wait_runners: bool = False,
    wait_runners: int | None = None,
    queue_capacity_multiplier: float | None = None,
    update_wait_priority: bool = False,
    wait_priority: int | None = None,
    update_queue_weight: bool = False,
    queue_weight: float | None = None,
    queue_weight_explicit: bool = False,
) -> AgentMetaPatch:
    """Build an ``agent_meta.json`` patch for a wait directive payload."""
    set_values: dict[str, object] = {}
    remove_keys = [
        "wait_for",
        "wait_for_epics_of",
        "wait_for_beads",
        "wait_for_hoods",
        "wait_duration",
        "wait_until",
    ]
    if wait_names:
        set_values["wait_for"] = list(_durable_wait_names(wait_names))
    if wait_for_epics_of:
        set_values["wait_for_epics_of"] = list(_durable_wait_names(wait_for_epics_of))
    if wait_beads:
        set_values["wait_for_beads"] = list(wait_beads)
    if wait_hoods:
        set_values["wait_for_hoods"] = list(wait_hoods)
    if time_token:
        duration = parse_duration(time_token)
        if duration is not None:
            set_values["wait_duration"] = duration
        else:
            wait_until = parse_absolute_time(time_token)
            if wait_until is not None:
                set_values["wait_until"] = wait_until
    if update_wait_runners:
        remove_keys.extend(
            (
                "wait_runners",
                "wait_runners_explicit",
                "queue_capacity",
                "queue_capacity_explicit",
                "queue_capacity_multiplier",
            )
        )
        if wait_runners is not None:
            set_values["queue_capacity"] = wait_runners
            set_values["queue_capacity_explicit"] = True
        elif queue_capacity_multiplier is not None:
            set_values["queue_capacity_multiplier"] = queue_capacity_multiplier
    if update_wait_priority:
        remove_keys.append("wait_priority")
        if wait_priority is not None:
            set_values["wait_priority"] = wait_priority
    if update_queue_weight:
        remove_keys.extend(("queue_weight", "queue_weight_explicit"))
        if queue_weight is not None:
            set_values["queue_weight"] = queue_weight
            set_values["queue_weight_explicit"] = queue_weight_explicit
    return AgentMetaPatch(set_values=set_values, remove_keys=tuple(remove_keys))


def waiting_marker_patch_for_token(
    *,
    wait_names: tuple[str, ...] = (),
    wait_for_epics_of: tuple[str, ...] = (),
    wait_beads: tuple[str, ...] = (),
    wait_hoods: tuple[str, ...] = (),
    time_token: str | None = None,
    update_wait_runners: bool = False,
    wait_runners: int | None = None,
    queue_capacity_multiplier: float | None = None,
    update_wait_priority: bool = False,
    wait_priority: int | None = None,
    update_queue_weight: bool = False,
    queue_weight: float | None = None,
    queue_weight_explicit: bool = False,
) -> WaitingMarkerPatch:
    """Build a ``waiting.json`` replacement for a wait directive payload."""
    wait_duration: float | None = None
    wait_until: str | None = None
    if time_token:
        wait_duration = parse_duration(time_token)
        if wait_duration is None:
            wait_until = parse_absolute_time(time_token)
    return WaitingMarkerPatch(
        waiting_for=_durable_wait_names(wait_names),
        wait_for_epics_of=_durable_wait_names(wait_for_epics_of),
        wait_for_beads=wait_beads,
        wait_for_hoods=wait_hoods,
        wait_duration=wait_duration,
        wait_until=wait_until,
        update_wait_runners=update_wait_runners,
        wait_runners=wait_runners,
        queue_capacity_multiplier=queue_capacity_multiplier,
        update_wait_priority=update_wait_priority,
        wait_priority=wait_priority,
        update_queue_weight=update_queue_weight,
        queue_weight=queue_weight,
        queue_weight_explicit=queue_weight_explicit,
    )


def _durable_wait_names(wait_names: tuple[str, ...]) -> tuple[str, ...]:
    """Qualify agent dependencies while leaving tribe references unchanged."""
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        normalize_owned_agent_name,
    )

    identity = AgentIdentitySnapshot.current()
    return tuple(
        name if name.startswith("@") else normalize_owned_agent_name(name, identity)
        for name in wait_names
    )


__all__ = [
    "wait_meta_patch_for_token",
    "waiting_marker_patch_for_token",
]
