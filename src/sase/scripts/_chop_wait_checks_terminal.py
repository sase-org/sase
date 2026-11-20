"""Terminal-blocker detection and notification for wait_checks."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.time import get_timezone
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    read_json_dict as _read_json_dict,
)
from sase.agent.auto_restart.forward import recovery_in_flight
from sase.core.wait_dependency_resolution._artifact_state import artifact_dir_key
from sase.core.wait_dependency_resolution._epic_follow import EpicFollowDecision
from sase.core.wait_dependency_resolution._types import ArtifactCandidate
from sase.core.stranded_work_facade import StrandedWorkVerdict
from sase.bead.stranded_presentation import (
    stranded_age_label,
    stranded_cause_sentence,
)
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import (
    load_notifications,
    mark_dismissed,
    upsert_notification,
)
from sase.scripts._chop_wait_checks_common import (
    StrandedBeadWaiter,
    TerminalBlocker,
    WaitingMarker,
)

_TERMINAL_BLOCKED_WAIT_SENDER = "wait_checks"

# Dedup-key namespace for epic-follow blocker notifications. Keys are per
# waiter and target (or epic), so each case produces exactly one entry with
# +1 corroboration on repeat ticks.
_EPIC_FOLLOW_DEDUP_PREFIX = "wait_checks:epic-follow-"
_STRANDED_BEAD_DEDUP_PREFIX = "wait_checks:stranded-bead:"

# Mirrors the collector's ``launching_grace_seconds`` default: a LAUNCHING
# follow stays quiet until its ``since`` is older than this.
_LAUNCHING_GRACE_SECONDS = 600.0


def terminal_blockers(
    dependency_index: WaitDependencyIndex,
    waiting_for: list[object],
    wait_for_artifacts: list[object],
    wait_for_hoods: list[object],
    blocked_on: tuple[str, ...],
    *,
    self_artifact_dir: Path,
) -> tuple[TerminalBlocker, ...]:
    blocked_labels = frozenset(blocked_on)
    blockers: list[TerminalBlocker] = []
    identity_names: set[str] = set()

    for dependency in wait_for_artifacts:
        if not isinstance(dependency, Mapping):
            continue
        name = dependency.get("name")
        if isinstance(name, str) and name:
            identity_names.add(name)
        label = _dependency_label(dependency)
        if label not in blocked_labels:
            continue
        candidate = _artifact_candidate_for_identity(dependency_index, dependency)
        if candidate is not None and _identity_terminal_blocker(candidate):
            if recovery_in_flight(candidate.artifact_dir):
                continue
            outcome = candidate.outcome
            assert outcome is not None
            blockers.append(
                TerminalBlocker(
                    dependency=label,
                    artifact_dir=candidate.artifact_dir,
                    outcome=outcome,
                    blocker_name=candidate.name or None,
                )
            )

    waiter_launch_cutoff = self_artifact_dir.name
    for hood in wait_for_hoods:
        if not isinstance(hood, str):
            continue
        label = f"hood={hood}"
        if label not in blocked_labels:
            continue
        for candidate in dependency_index.terminal_blocking_artifacts_for_hood(
            hood,
            exclude_artifact_dir=self_artifact_dir,
            launched_at_or_before=waiter_launch_cutoff,
        ):
            if recovery_in_flight(candidate.artifact_dir):
                continue
            assert candidate.outcome is not None
            blockers.append(
                TerminalBlocker(
                    dependency=label,
                    artifact_dir=candidate.artifact_dir,
                    outcome=candidate.outcome,
                    blocker_name=candidate.name or None,
                )
            )

    for name in waiting_for:
        if not isinstance(name, str) or name in identity_names:
            continue
        if name not in blocked_labels:
            continue
        for candidate in dependency_index.terminal_blocking_artifacts_for_name(
            name,
            exclude_artifact_dir=self_artifact_dir,
            newer_than=waiter_launch_cutoff if name.startswith("@") else None,
        ):
            if recovery_in_flight(candidate.artifact_dir):
                continue
            assert candidate.outcome is not None
            blockers.append(
                TerminalBlocker(
                    dependency=name,
                    artifact_dir=candidate.artifact_dir,
                    outcome=candidate.outcome,
                    blocker_name=candidate.name or None,
                )
            )

    return tuple(blockers)


def pending_upstream_dirs(
    dependency_index: WaitDependencyIndex,
    waiting_for: list[object],
    wait_for_artifacts: list[object],
    wait_for_hoods: list[object],
    blocked_on: tuple[str, ...],
    *,
    self_artifact_dir: Path,
) -> frozenset[str]:
    """Return keys of not-yet-finished members that block this waiter.

    Mirrors :func:`terminal_blockers` label for label, but returns the
    members that may still run instead of failed ones. A live waiter among
    them blocks this waiter for as long as it stays parked, which is how a
    waiter inherits its upstream waiter's root terminal blocker.
    """
    blocked_labels = frozenset(blocked_on)
    keys: set[str] = set()
    identity_names: set[str] = set()

    for dependency in wait_for_artifacts:
        if not isinstance(dependency, Mapping):
            continue
        name = dependency.get("name")
        if isinstance(name, str) and name:
            identity_names.add(name)
        if _dependency_label(dependency) not in blocked_labels:
            continue
        candidate = _artifact_candidate_for_identity(dependency_index, dependency)
        if candidate is not None and not candidate.has_done_marker:
            keys.add(artifact_dir_key(candidate.artifact_dir))

    waiter_launch_cutoff = self_artifact_dir.name
    for hood in wait_for_hoods:
        if not isinstance(hood, str) or f"hood={hood}" not in blocked_labels:
            continue
        for candidate in dependency_index.pending_blocking_members_for_hood(
            hood,
            exclude_artifact_dir=self_artifact_dir,
            launched_at_or_before=waiter_launch_cutoff,
        ):
            keys.add(artifact_dir_key(candidate.artifact_dir))

    for name in waiting_for:
        if not isinstance(name, str) or name in identity_names:
            continue
        if name not in blocked_labels:
            continue
        for candidate in dependency_index.pending_blocking_members_for_name(
            name,
            exclude_artifact_dir=self_artifact_dir,
            newer_than=waiter_launch_cutoff if name.startswith("@") else None,
        ):
            keys.add(artifact_dir_key(candidate.artifact_dir))

    keys.discard(artifact_dir_key(str(self_artifact_dir)))
    return frozenset(keys)


def stranded_bead_wait_dedup_key(project: str, bead_id: str) -> str:
    """Return the single shared wait notification key for a stranded bead."""
    return f"{_STRANDED_BEAD_DEDUP_PREFIX}{project}:{bead_id}"


def _parse_stranded_bead_wait_dedup_key(key: str | None) -> tuple[str, str] | None:
    """Return ``(project, bead_id)`` from a canonical stranded-bead wait key."""
    if not isinstance(key, str) or not key.startswith(_STRANDED_BEAD_DEDUP_PREFIX):
        return None
    remainder = key.removeprefix(_STRANDED_BEAD_DEDUP_PREFIX)
    project, sep, bead_id = remainder.partition(":")
    project = project.strip()
    bead_id = bead_id.strip()
    if not sep or not project or not bead_id:
        return None
    return project, bead_id


def outstanding_stranded_bead_wait_targets() -> dict[str, set[str]]:
    """Group undismissed stranded-bead wait alerts by project and bead ID."""
    targets: dict[str, set[str]] = {}
    for row in load_notifications():
        if row.sender != _TERMINAL_BLOCKED_WAIT_SENDER:
            continue
        parsed = _parse_stranded_bead_wait_dedup_key(row.dedup_key)
        if parsed is None:
            continue
        project, bead_id = parsed
        targets.setdefault(project, set()).add(bead_id)
    return targets


def upsert_stranded_bead_wait_notification(
    project: str,
    verdict: StrandedWorkVerdict,
    title: str,
    waiters: tuple[StrandedBeadWaiter, ...],
    *,
    now: float,
) -> None:
    """Upsert one notification for a stranded bead with live waiters."""
    timestamp = datetime.now(get_timezone()).isoformat()
    waiter_lines = [
        f"{waiter.name} ({waiter.artifact_dir})"
        for waiter in sorted(waiters, key=lambda item: (item.name, item.artifact_dir))
    ]
    last_turn = verdict.last_turn or "unknown"
    age = stranded_age_label(verdict.since, now)
    last_turn_note = f"Last turn: {last_turn}"
    if age:
        last_turn_note += f" ({age} ago)"
    notes = [
        f"Stranded bead: {verdict.bead_id} — {title or '(untitled)'}",
        f"Cause: {stranded_cause_sentence(verdict)}",
        last_turn_note,
        f"Waiters blocked: {', '.join(waiter_lines)}",
    ]
    if verdict.kind == "phase":
        if verdict.parent_id:
            notes.append(
                "Relaunch with: `sase bead work "
                f"{verdict.parent_id} --yes-to-all` "
                "(relaunches every non-closed phase and the land agent)."
            )
        else:
            notes.append(
                "Relaunch the parent epic with `sase bead work <epic-id> "
                "--yes-to-all` (relaunches every non-closed phase and the land agent)."
            )
    else:
        notes.append(f"Relaunch with: `sase bead work {verdict.bead_id} --yes`.")
    notes.append(
        f"When the work is actually done, close it with `sase bead close "
        f'{verdict.bead_id} --note "<what you verified>"`.'
    )

    files = [waiter.artifact_dir for waiter in waiters]
    if verdict.last_turn_artifact_dir:
        files.append(verdict.last_turn_artifact_dir)
    action = None
    action_data: dict[str, str] = {}
    if verdict.last_turn and verdict.last_turn_artifact_dir:
        action = "JumpToAgent"
        action_data = {
            "cl_name": verdict.last_turn,
            "raw_suffix": Path(verdict.last_turn_artifact_dir).name,
        }
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender=_TERMINAL_BLOCKED_WAIT_SENDER,
        icon="!",
        color="#D14343",
        notes=notes,
        files=list(dict.fromkeys(files)),
        tags=normalize_notification_tags(["wait", "blocked", "stranded"]),
        action=action,
        action_data=action_data,
        dedup_key=stranded_bead_wait_dedup_key(project, verdict.bead_id),
    )
    upsert_notification(
        notification,
        plus_one_note=f"Still blocked waiters: {', '.join(waiter_lines)}",
        plus_one_timestamp=timestamp,
    )


def waiter_display_name(
    waiter_dir: Path,
    meta: Mapping[str, Any] | None = None,
    *,
    meta_known: bool = False,
) -> str:
    """Return the waiter's agent name, falling back to its directory name.

    Reads ``agent_meta.json`` unless ``meta_known`` says ``meta`` already
    holds that file's parsed contents (``None`` when missing or invalid).
    Never returns ``cl_name`` or any other project directory key: the meta
    ``name`` is the agent identity, while ``cl_name`` is the project key
    for ordinary ``ace(run)`` agents.
    """
    if not meta_known:
        try:
            meta = _read_json_dict(waiter_dir / "agent_meta.json")
        except Exception:
            meta = None
    if isinstance(meta, Mapping):
        name = meta.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return waiter_dir.name


def _waiting_agent_label(waiting_data: Mapping[str, Any], waiter_dir: Path) -> str:
    return waiter_display_name(waiter_dir)


def _artifact_candidate_for_identity(
    dependency_index: WaitDependencyIndex,
    dependency: Mapping[str, Any],
) -> ArtifactCandidate | None:
    artifact_dir = dependency.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir:
        candidate = dependency_index.artifacts_by_dir.get(artifact_dir)
        if candidate is not None:
            return candidate

    project_name = dependency.get("project_name")
    timestamp = dependency.get("timestamp")
    if isinstance(project_name, str) and isinstance(timestamp, str):
        return dependency_index.artifacts.get((project_name, timestamp))
    return None


def _identity_terminal_blocker(candidate: ArtifactCandidate) -> bool:
    return (
        candidate.has_done_marker
        and candidate.outcome is not None
        and not candidate.is_identity_success
    )


def _dependency_label(dependency: Mapping[str, Any]) -> str:
    artifact_dir = dependency.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir:
        return artifact_dir
    project_name = dependency.get("project_name")
    timestamp = dependency.get("timestamp")
    if (
        isinstance(project_name, str)
        and project_name
        and isinstance(timestamp, str)
        and timestamp
    ):
        return f"{project_name}:{timestamp}"
    name = dependency.get("name")
    if isinstance(name, str) and name:
        return name
    return "<artifact dependency>"


def epic_follow_launching_dedup_key(waiter_dir: str, target: str) -> str:
    return f"{_EPIC_FOLLOW_DEDUP_PREFIX}launching:{waiter_dir}:{target}"


def epic_follow_blocked_dedup_key(waiter_dir: str, target: str) -> str:
    return f"{_EPIC_FOLLOW_DEDUP_PREFIX}blocked:{waiter_dir}:{target}"


def epic_follow_land_failed_dedup_key(waiter_dir: str, epic_id: str) -> str:
    return f"{_EPIC_FOLLOW_DEDUP_PREFIX}land-failed:{waiter_dir}:{epic_id}"


def _grace_label(seconds: float = _LAUNCHING_GRACE_SECONDS) -> str:
    if seconds >= 60 and seconds % 60 == 0:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds)}s"


def _approved_label(since: float) -> str:
    try:
        return datetime.fromtimestamp(since, tz=get_timezone()).strftime("%H:%M")
    except (OSError, OverflowError, ValueError):
        return "unknown"


def upsert_epic_follow_launching_notification(
    waiting_marker: WaitingMarker,
    waiting_data: Mapping[str, Any],
    decision: EpicFollowDecision,
) -> None:
    """Notify once that a LAUNCHING follow is past its grace period.

    Only overdue launches notify; a fresh reservation stays quiet. Repeat
    ticks corroborate the single entry via +1.
    """
    waiter_dir = waiting_marker.waiting_path.parent
    waiter_name = _waiting_agent_label(waiting_data, waiter_dir)
    timestamp = datetime.now(get_timezone()).isoformat()
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender=_TERMINAL_BLOCKED_WAIT_SENDER,
        icon="!",
        color="#D14343",
        notes=[
            "Epic-follow launch is overdue",
            f"Waiter: {waiter_name}",
            (
                f"{waiter_name} is waiting on {decision.target}'s epic launch "
                f"(approved {_approved_label(decision.since)}; "
                f"no epic after {_grace_label()})"
            ),
            (
                "The planner was approved but no epic appeared; check whether "
                "the epic launch stalled."
            ),
        ],
        files=[str(waiter_dir)],
        tags=normalize_notification_tags(["wait", "blocked", "epic-follow"]),
        dedup_key=epic_follow_launching_dedup_key(str(waiter_dir), decision.target),
    )
    upsert_notification(
        notification,
        plus_one_note=(
            f"Still waiting on {decision.target}'s epic launch: "
            f"no epic after {_grace_label()}"
        ),
        plus_one_timestamp=timestamp,
    )


def upsert_epic_follow_blocked_notification(
    waiting_marker: WaitingMarker,
    waiting_data: Mapping[str, Any],
    decision: EpicFollowDecision,
) -> None:
    """Notify once that an epic follow is BLOCKED, with the resume command.

    The entry jumps to the waiter so the operator can resume or clear the
    wait from there.
    """
    waiter_dir = waiting_marker.waiting_path.parent
    waiter_name = _waiting_agent_label(waiting_data, waiter_dir)
    timestamp = datetime.now(get_timezone()).isoformat()
    reason = decision.detail or decision.reason or "unknown reason"
    notes = [
        "Epic follow is blocked",
        f"Waiter: {waiter_name}",
        f"Target: {decision.target}",
        reason,
    ]
    if decision.resume_command:
        notes.append(f"Resume with: `{decision.resume_command}`")
    else:
        notes.append(
            "No resume command is known; inspect the target agent's "
            "epic launch and relaunch it if needed."
        )
    cl_name = waiting_data.get("cl_name")
    if not isinstance(cl_name, str) or not cl_name:
        cl_name = waiter_dir.name
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender=_TERMINAL_BLOCKED_WAIT_SENDER,
        icon="!",
        color="#D14343",
        notes=notes,
        files=[str(waiter_dir)],
        tags=normalize_notification_tags(["wait", "blocked", "epic-follow"]),
        action="JumpToAgent",
        action_data={
            "cl_name": cl_name,
            "raw_suffix": waiter_dir.name,
        },
        dedup_key=epic_follow_blocked_dedup_key(str(waiter_dir), decision.target),
    )
    upsert_notification(
        notification,
        plus_one_note=f"Still blocked on {decision.target}: {reason}",
        plus_one_timestamp=timestamp,
    )


def upsert_epic_follow_land_failed_notification(
    waiting_marker: WaitingMarker,
    waiting_data: Mapping[str, Any],
    epic_id: str,
    land_agent_name: str,
    land_artifact_dir: str,
    outcome: str,
) -> None:
    """Notify once that a followed epic's land agent failed terminally.

    The followed epic will never close on its own, so the wait cannot
    resolve without operator action.
    """
    waiter_dir = waiting_marker.waiting_path.parent
    waiter_name = _waiting_agent_label(waiting_data, waiter_dir)
    timestamp = datetime.now(get_timezone()).isoformat()
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender=_TERMINAL_BLOCKED_WAIT_SENDER,
        icon="!",
        color="#D14343",
        notes=[
            "Followed epic will never close",
            f"Waiter: {waiter_name}",
            (
                f"Epic {epic_id}: land agent {land_agent_name} "
                f"({land_artifact_dir}) ended {outcome}"
            ),
            (
                "Clear the epic follow or relaunch the epic; "
                "the wait cannot resolve on its own."
            ),
        ],
        files=[str(waiter_dir), land_artifact_dir],
        tags=normalize_notification_tags(["wait", "blocked", "epic-follow"]),
        dedup_key=epic_follow_land_failed_dedup_key(str(waiter_dir), epic_id),
    )
    upsert_notification(
        notification,
        plus_one_note=(
            f"Epic {epic_id} still unclosable: land agent {land_agent_name} ({outcome})"
        ),
        plus_one_timestamp=timestamp,
    )


def reconcile_epic_follow_notifications(
    active_dedup_keys: set[str],
    waiter_dirs: set[str],
) -> int:
    """Dismiss stale epic-follow entries for successfully evaluated waiters.

    A row is stale when its condition no longer holds (the follow moved to
    FOLLOWING/NONE, or the waiter released) and its waiter was evaluated
    this tick. Waiters that errored or deferred stay out of ``waiter_dirs``
    so their entries fail open. Returns the dismissed count.
    """
    if not waiter_dirs:
        return 0
    dismissed = 0
    for row in load_notifications():
        if row.sender != _TERMINAL_BLOCKED_WAIT_SENDER:
            continue
        key = row.dedup_key or ""
        if not key.startswith(_EPIC_FOLLOW_DEDUP_PREFIX):
            continue
        if key in active_dedup_keys:
            continue
        if not any(f":{waiter_dir}:" in key for waiter_dir in waiter_dirs):
            continue
        try:
            if mark_dismissed(row.id):
                dismissed += 1
        except Exception:
            continue
    return dismissed


def reconcile_stranded_bead_wait_notifications(
    dismiss_dedup_keys: set[str],
) -> int:
    """Dismiss only stranded-bead rows whose bead state was freshly resolved."""
    if not dismiss_dedup_keys:
        return 0
    dismissed = 0
    for row in load_notifications():
        if row.sender != _TERMINAL_BLOCKED_WAIT_SENDER:
            continue
        if row.dedup_key not in dismiss_dedup_keys:
            continue
        try:
            if mark_dismissed(row.id):
                dismissed += 1
        except Exception:
            continue
    return dismissed


__all__ = [
    "epic_follow_blocked_dedup_key",
    "epic_follow_land_failed_dedup_key",
    "epic_follow_launching_dedup_key",
    "outstanding_stranded_bead_wait_targets",
    "reconcile_epic_follow_notifications",
    "reconcile_stranded_bead_wait_notifications",
    "stranded_bead_wait_dedup_key",
    "pending_upstream_dirs",
    "terminal_blockers",
    "upsert_epic_follow_blocked_notification",
    "upsert_epic_follow_land_failed_notification",
    "upsert_epic_follow_launching_notification",
    "upsert_stranded_bead_wait_notification",
    "waiter_display_name",
]
