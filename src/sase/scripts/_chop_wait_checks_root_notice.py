"""One wait_checks notice per failed root blocker.

Each root terminal blocker gets one row keyed
``wait_checks:terminal-blocker:{root artifact_dir}`` that names the blocker,
its outcome, and every direct and transitive waiter. A pass whose rendered
row matches the stored one writes nothing, so the row never collects ``+1``
evidence for an unchanged blockage. A changed waiter set refreshes the row
in place through the field-scoped reconcile path, and the row turns unread
again only when a waiter joins. When every waiter is gone the job dismisses
the row with the reversible ``wait_checks_auto_dismissed`` marker, so a
returning waiter resurfaces it unread. Legacy per-waiter rows
(``wait_checks:terminal-blocked:{waiter_dir}``) settle once with the same
marker when a root notice covers their waiter or the waiter is no longer
live.

``action_data`` contract (string values, read by the waiter-expire action):

- ``blocker_artifact_dir``, ``blocker_outcome``, ``blocker_dependency``, and
  ``blocker_name`` (empty when unknown) describe the root blocker.
- ``waiter_count`` is the decimal length of ``waiters``.
- ``waiters`` is a JSON list of objects with ``artifact_dir``, ``name``, and
  ``project`` keys, plus ``via`` (the upstream waiter's artifact dir) for a
  transitive waiter.
- ``wait_checks_auto_dismissed`` is ``"true"`` only while the job itself
  settled the row.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.time import get_timezone
from sase.core.wait_dependency_resolution import read_json_dict
from sase.core.wait_dependency_resolution._artifact_state import artifact_dir_key
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import (
    load_notifications,
    reconcile_notification_rows,
    upsert_notification,
)
from sase.scripts._chop_wait_checks_common import TerminalBlocker
from sase.scripts._chop_wait_checks_roots import RootGroup, RootWaiter

WAIT_CHECKS_SENDER = "wait_checks"
ROOT_BLOCKER_DEDUP_PREFIX = "wait_checks:terminal-blocker:"
LEGACY_WAITER_DEDUP_PREFIX = "wait_checks:terminal-blocked:"
AUTO_DISMISSED_ACTION_DATA_KEY = "wait_checks_auto_dismissed"

#: Waiters named one per note line before the rest collapse into a count.
MAX_WAITER_NOTE_LINES = 20


@dataclass
class _RootNoticeOutcome:
    """Row counts written by one root-blocker reconcile pass."""

    created: int = 0
    updated: int = 0
    resurfaced: int = 0
    settled: int = 0
    legacy_settled: int = 0

    def changed(self) -> bool:
        return bool(
            self.created
            or self.updated
            or self.resurfaced
            or self.settled
            or self.legacy_settled
        )


def _root_blocker_dedup_key(blocker_artifact_dir: str) -> str:
    """Return the single notice key for one root terminal blocker."""
    return f"{ROOT_BLOCKER_DEDUP_PREFIX}{blocker_artifact_dir}"


def _build_root_blocker_notification(
    group: RootGroup,
    *,
    notification_id: str,
    timestamp: str,
) -> Notification:
    """Render the deterministic notice for one root group."""
    blocker = group.blocker
    waiters = _ordered_waiters(group)
    if blocker.blocker_name and blocker.blocker_name != blocker.dependency:
        blocked_line = (
            f"Blocked on {blocker.dependency} ({blocker.blocker_name}): "
            f"{blocker.artifact_dir} ({blocker.outcome})"
        )
    else:
        blocked_line = (
            f"Blocked on {blocker.dependency}: {blocker.artifact_dir} "
            f"({blocker.outcome})"
        )
    notes = [
        "Wait dependency can never self-resolve",
        blocked_line,
        f"Waiters blocked: {len(waiters)}",
    ]
    for waiter in waiters[:MAX_WAITER_NOTE_LINES]:
        if waiter.via is None:
            notes.append(f"Waiter: {waiter.name}")
        else:
            notes.append(f"Waiter: {waiter.name} (via {waiter.via_name or waiter.via})")
    if len(waiters) > MAX_WAITER_NOTE_LINES:
        notes.append(f"…and {len(waiters) - MAX_WAITER_NOTE_LINES} more waiter(s)")
    notes.append(
        "Kill and relaunch the waiters, or intentionally clear their waits "
        "once the dependency state is understood."
    )
    files = [blocker.artifact_dir, *(waiter.artifact_dir for waiter in waiters)]
    resume_command, snapshot_path = _monitor_not_launchable_recovery(
        blocker.artifact_dir
    )
    if resume_command:
        notes.append(f"Monitor recovery: `{resume_command}`")
    if snapshot_path:
        notes.append(f"Worktree recovery diff: {snapshot_path}")
        files.append(snapshot_path)
    return Notification(
        id=notification_id,
        timestamp=timestamp,
        sender=WAIT_CHECKS_SENDER,
        icon="!",
        color="#D14343",
        notes=notes,
        files=list(dict.fromkeys(files)),
        tags=normalize_notification_tags(["wait", "blocked", "terminal-dependency"]),
        action_data={
            "blocker_artifact_dir": blocker.artifact_dir,
            "blocker_outcome": blocker.outcome,
            "blocker_dependency": blocker.dependency,
            "blocker_name": blocker.blocker_name or "",
            "waiter_count": str(len(waiters)),
            "waiters": json.dumps(
                [_waiter_payload(waiter) for waiter in waiters],
                separators=(",", ":"),
            ),
        },
        dedup_key=_root_blocker_dedup_key(blocker.artifact_dir),
    )


def reconcile_root_blocker_notifications(
    groups: Mapping[str, RootGroup],
    *,
    fail_open_dirs: Collection[str],
    live_waiter_dirs: Collection[str],
) -> _RootNoticeOutcome:
    """Publish, refresh, and settle root-blocker and legacy per-waiter rows.

    ``groups`` come from :func:`group_by_root_blocker`. ``fail_open_dirs``
    holds keys of live waiters whose release check did not complete this
    tick; a stored waiter among them stays listed instead of being dropped.
    ``live_waiter_dirs`` holds keys of every live parked waiter, which keeps
    an uncovered legacy row in place while its waiter may still notify.
    """
    outcome = _RootNoticeOutcome()
    root_rows, legacy_rows = _wait_checks_rows(include_dismissed=bool(groups))
    open_root_keys = {key for key, row in root_rows.items() if not row.dismissed}
    if not groups and not open_root_keys and not legacy_rows:
        return outcome

    timestamp = datetime.now(get_timezone()).isoformat()
    covered: set[str] = set()
    flip_rows: list[Notification] = []
    write_rows: list[Notification] = []
    for root_key in sorted(set(groups) | open_root_keys):
        existing = root_rows.get(root_key)
        group = _effective_group(groups.get(root_key), existing, fail_open_dirs)
        if group is None or not group.waiters:
            if existing is not None and not existing.dismissed:
                write_rows.append(_auto_dismissed(existing))
                outcome.settled += 1
            continue
        covered.update(group.waiters)
        if existing is None:
            desired = _build_root_blocker_notification(
                group, notification_id=str(uuid4()), timestamp=timestamp
            )
            # A concurrent tick may have created the row since the load;
            # the store's +1 guard coalesces that race.
            upsert_notification(
                desired,
                plus_one_note=(
                    f"Still blocked: {len(group.waiters)} waiter(s) on "
                    f"{group.blocker.artifact_dir} ({group.blocker.outcome})"
                ),
                plus_one_timestamp=timestamp,
            )
            outcome.created += 1
            continue
        desired = _build_root_blocker_notification(
            group, notification_id=existing.id, timestamp=existing.timestamp
        )
        if existing.dismissed:
            if _has_auto_dismissed_marker(existing):
                # A settled root has waiters again: resurface it unread.
                write_rows.append(desired)
                outcome.resurfaced += 1
            elif not _same_content(existing, desired):
                # A user dismissal holds; keep the content accurate.
                write_rows.append(desired)
                outcome.updated += 1
            continue
        if _same_content(existing, desired):
            continue
        joined = set(group.waiters) - _stored_waiter_keys(existing)
        if joined and existing.read:
            # The store has no direct mark-unread update: dismiss with the
            # reversible marker, then resurface, which clears ``read``. A
            # crash between the writes self-heals because the next pass
            # sees a marker-dismissed root that still has waiters.
            flip_rows.append(_auto_dismissed(desired))
            outcome.resurfaced += 1
        else:
            outcome.updated += 1
        write_rows.append(desired)

    for row in legacy_rows:
        waiter_dir = (row.dedup_key or "").removeprefix(LEGACY_WAITER_DEDUP_PREFIX)
        waiter_key = artifact_dir_key(waiter_dir) if waiter_dir else ""
        if waiter_key and waiter_key not in covered and waiter_key in live_waiter_dirs:
            continue
        write_rows.append(_auto_dismissed(row))
        outcome.legacy_settled += 1

    for rows in (flip_rows, write_rows):
        if rows:
            reconcile_notification_rows(
                rows,
                reversible_dismiss_marker_key=AUTO_DISMISSED_ACTION_DATA_KEY,
                refresh_files=True,
            )
    return outcome


def _wait_checks_rows(
    *, include_dismissed: bool
) -> tuple[dict[str, Notification], list[Notification]]:
    """Return root rows by blocker key and undismissed legacy rows."""
    root_rows: dict[str, Notification] = {}
    legacy_rows: list[Notification] = []
    for row in load_notifications(include_dismissed=include_dismissed):
        if row.sender != WAIT_CHECKS_SENDER:
            continue
        key = row.dedup_key or ""
        if key.startswith(ROOT_BLOCKER_DEDUP_PREFIX):
            root_dir = key.removeprefix(ROOT_BLOCKER_DEDUP_PREFIX)
            if not root_dir:
                continue
            root_key = artifact_dir_key(root_dir)
            current = root_rows.get(root_key)
            # Prefer an undismissed duplicate, then the newest one.
            if current is None or current.dismissed or not row.dismissed:
                root_rows[root_key] = row
        elif key.startswith(LEGACY_WAITER_DEDUP_PREFIX) and not row.dismissed:
            legacy_rows.append(row)
    return root_rows, legacy_rows


def _effective_group(
    group: RootGroup | None,
    existing: Notification | None,
    fail_open_dirs: Collection[str],
) -> RootGroup | None:
    """Keep stored waiters whose release check did not complete this tick."""
    if existing is None or existing.dismissed or not fail_open_dirs:
        return group
    carried = {
        key: waiter
        for waiter in _stored_waiters(existing)
        if (key := artifact_dir_key(waiter.artifact_dir)) in fail_open_dirs
        and (group is None or key not in group.waiters)
    }
    if not carried:
        return group
    if group is None:
        blocker = _stored_blocker(existing)
        if blocker is None:
            return None
        merged = RootGroup(blocker=blocker)
    else:
        merged = RootGroup(blocker=group.blocker, waiters=dict(group.waiters))
    merged.waiters.update(carried)
    return merged


def _ordered_waiters(group: RootGroup) -> list[RootWaiter]:
    return sorted(
        group.waiters.values(),
        key=lambda waiter: (waiter.via is not None, waiter.name, waiter.artifact_dir),
    )


def _waiter_payload(waiter: RootWaiter) -> dict[str, str]:
    payload = {
        "artifact_dir": waiter.artifact_dir,
        "name": waiter.name,
        "project": waiter.project_name,
    }
    if waiter.via is not None:
        payload["via"] = waiter.via
    return payload


def _stored_waiters(row: Notification) -> list[RootWaiter]:
    try:
        raw = json.loads(row.action_data.get("waiters", "[]"))
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    waiters: list[RootWaiter] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        artifact_dir = item.get("artifact_dir")
        if not isinstance(artifact_dir, str) or not artifact_dir:
            continue
        name = item.get("name")
        project = item.get("project")
        via = item.get("via")
        waiters.append(
            RootWaiter(
                artifact_dir=artifact_dir,
                name=name
                if isinstance(name, str) and name
                else Path(artifact_dir).name,
                project_name=project if isinstance(project, str) else "",
                via=via if isinstance(via, str) and via else None,
                via_name=Path(via).name if isinstance(via, str) and via else None,
            )
        )
    return waiters


def _stored_waiter_keys(row: Notification) -> set[str]:
    return {artifact_dir_key(waiter.artifact_dir) for waiter in _stored_waiters(row)}


def _stored_blocker(row: Notification) -> TerminalBlocker | None:
    data = row.action_data
    artifact_dir = data.get("blocker_artifact_dir")
    outcome = data.get("blocker_outcome")
    if not artifact_dir or not outcome:
        return None
    return TerminalBlocker(
        dependency=data.get("blocker_dependency") or artifact_dir,
        artifact_dir=artifact_dir,
        outcome=outcome,
        blocker_name=data.get("blocker_name") or None,
    )


def _has_auto_dismissed_marker(row: Notification) -> bool:
    return row.action_data.get(AUTO_DISMISSED_ACTION_DATA_KEY) == "true"


def _auto_dismissed(row: Notification) -> Notification:
    return dataclasses.replace(
        row,
        dismissed=True,
        action_data={**row.action_data, AUTO_DISMISSED_ACTION_DATA_KEY: "true"},
    )


def _same_content(existing: Notification, desired: Notification) -> bool:
    existing_data = dict(existing.action_data)
    existing_data.pop(AUTO_DISMISSED_ACTION_DATA_KEY, None)
    return (
        existing.notes == desired.notes
        and existing.files == desired.files
        and existing.tags == desired.tags
        and existing.icon == desired.icon
        and existing.color == desired.color
        and existing.action == desired.action
        and existing.silent == desired.silent
        and existing_data == desired.action_data
    )


def _monitor_not_launchable_recovery(
    artifact_dir: str,
) -> tuple[str | None, str | None]:
    """Return the resume command and recovery diff for a stranded monitor."""
    done = read_json_dict(Path(artifact_dir) / "done.json")
    if done is None or done.get("monitor_followup_outcome") != "not-launchable":
        return None, None
    meta = read_json_dict(Path(artifact_dir) / "agent_meta.json") or {}
    monitor_id = _string_value(done.get("monitor_id")) or _string_value(
        meta.get("monitor_id")
    )
    snapshot_path = _string_value(
        done.get("monitor_worktree_recovery_diff_path")
    ) or _string_value(meta.get("monitor_worktree_recovery_diff_path"))
    resume_command = f"sase monitor resume {monitor_id}" if monitor_id else None
    return resume_command, snapshot_path


def _string_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "AUTO_DISMISSED_ACTION_DATA_KEY",
    "LEGACY_WAITER_DEDUP_PREFIX",
    "MAX_WAITER_NOTE_LINES",
    "ROOT_BLOCKER_DEDUP_PREFIX",
    "reconcile_root_blocker_notifications",
]
