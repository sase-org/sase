"""Launch-name preflight for ``sase bead work`` before bead-store mutations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.names._forced_reuse import ForcedReuseCleanupError

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder


def preflight_bead_work_launch_names(
    launch_names: Iterable[str],
    *,
    resume_command: str,
    timer: LaunchTimingRecorder | None = None,
) -> None:
    """Fail fast when planned launch names are still owned in the registry.

    Raises :class:`ForcedReuseCleanupError` with owner details and the resume
    command. Never applies reservations and never includes the planner's
    ``try 'X.N'`` suggestion.
    """
    names = tuple(launch_names)
    if not names:
        return
    if timer is None:
        _preflight_bead_work_launch_names(names, resume_command=resume_command)
        return
    with timer.stage("launch_name_preflight", name_count=len(names)):
        _preflight_bead_work_launch_names(names, resume_command=resume_command)


def explain_bead_work_launch_name_collision(
    exc: BaseException,
    launch_names: Iterable[str],
    *,
    resume_command: str,
    timer: LaunchTimingRecorder | None = None,
) -> str | None:
    """Return a launch-collision explanation after rollback, or ``None``.

    When *exc* is a :class:`~sase.agent.names.NameCollisionError`, re-run
    preflight so the message names the current owner. If that owner is gone,
    keep the original collision text and add the resume command.
    """
    from sase.agent.names import NameCollisionError

    if not isinstance(exc, NameCollisionError):
        return None
    try:
        preflight_bead_work_launch_names(
            launch_names,
            resume_command=resume_command,
            timer=timer,
        )
    except ForcedReuseCleanupError as preflight_exc:
        return str(preflight_exc)
    return (
        f"{exc}\n"
        f"No bead state was changed; rerun `{resume_command}` to review this owner."
    )


def _preflight_bead_work_launch_names(
    names: tuple[str, ...],
    *,
    resume_command: str,
) -> None:
    from sase.agent.names import (
        RegisteredNameReservation,
        plan_registered_name_reservations,
        registered_name_reservation_snapshot,
    )
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        normalize_owned_agent_name,
    )
    from sase.core.paths import sase_projects_dir

    identity = AgentIdentitySnapshot.current()
    names_by_request_id: dict[str, str] = {}
    reservations: list[RegisteredNameReservation] = []
    for index, raw_name in enumerate(names):
        name = normalize_owned_agent_name(raw_name, identity)
        request_id = f"bead-work-preflight-{index}"
        names_by_request_id[request_id] = name
        reservations.append(
            RegisteredNameReservation(
                request_id=request_id,
                operation="reserve_planned",
                name=name,
                artifact_dir=_synthetic_preflight_artifact_dir(
                    sase_projects_dir(), name
                ),
            )
        )

    planned = plan_registered_name_reservations(reservations)
    if not planned.blocked:
        return

    snapshot = registered_name_reservation_snapshot()
    lines: list[str] = []
    seen: set[str] = set()
    for item in planned.blocked:
        name = _blocked_name(item, names_by_request_id)
        if name in seen:
            continue
        seen.add(name)
        lines.append(_owned_name_line(name, snapshot.lookup(name)))
    if not lines:
        lines.append(
            "planned launch names are still owned and were not selected for cleanup"
        )
    lines.append(
        f"No bead state was changed; rerun `{resume_command}` to review this owner."
    )
    raise ForcedReuseCleanupError("\n".join(lines))


def _synthetic_preflight_artifact_dir(projects_dir: Path, name: str) -> Path:
    return projects_dir / "_bead_work_launch_name_preflight" / name


def _blocked_name(
    item: Mapping[str, Any],
    names_by_request_id: Mapping[str, str],
) -> str:
    request_id = item.get("request_id")
    if isinstance(request_id, str) and request_id in names_by_request_id:
        return names_by_request_id[request_id]
    raw_name = item.get("name")
    if isinstance(raw_name, str) and raw_name:
        return raw_name
    return "unknown"


def _owned_name_line(name: str, entry: Mapping[str, Any] | None) -> str:
    location = _owner_location(entry)
    state = _entry_str(entry, "state") or "unknown"
    kind = _owner_kind(entry)
    return (
        f"agent name '{name}' is still owned by {location} "
        f"(state={state}, kind={kind}) and was not selected for cleanup"
    )


def _owner_location(entry: Mapping[str, Any] | None) -> str:
    for key in ("artifacts_dir", "bundle_path"):
        value = _entry_str(entry, key)
        if value is not None:
            return value
    return "an unrecorded location"


def _owner_kind(entry: Mapping[str, Any] | None) -> str:
    for key in ("container_kind", "reservation_kind"):
        value = _entry_str(entry, key)
        if value is not None:
            return value
    return "unknown"


def _entry_str(entry: Mapping[str, Any] | None, key: str) -> str | None:
    if entry is None:
        return None
    value = entry.get(key)
    if isinstance(value, str) and value:
        return value
    return None
