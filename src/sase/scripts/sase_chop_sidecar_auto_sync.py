#!/usr/bin/env python3
"""Fetch and fast-forward opted-in primary sidecar clones, project-wide.

The generic backstop half of primary-sidecar auto-sync: it scans every
enabled project and every ``auto_sync`` sidecar role (plans, beads, research,
and arbitrary custom roles), preferring roles with a pending sync hint but
otherwise re-checking each role only every ``_BACKSTOP_INTERVAL_SECONDS``.
Only ``sase._sidecar_auto_sync.sync_primary_sidecar_role`` touches a clone,
and only to fetch and fast-forward a clean, attached, non-diverged checkout.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sase._sidecar_auto_sync import (
    SidecarSyncResult,
    auto_sync_roles,
    sync_primary_sidecar_role,
)
from sase._sidecar_sync_hints import clear_sidecar_sync_hint, pending_sidecar_sync_roles
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire

_BACKOFF_STATE_FILENAME = "sidecar_auto_sync_schedule.json"
# Keep in sync with the ``sidecar_auto_sync`` chop timeout in default_config.yml.
# The chop is SIGKILLed at that deadline, so every sync this run attempts has
# to fit inside it; the whole pass declines once it has spent the work budget.
_CHOP_TIMEOUT_SECONDS = 120.0
_WORK_BUDGET_SECONDS = 0.75 * _CHOP_TIMEOUT_SECONDS
_MAX_BACKOFF_SECONDS = 30 * 60
# A role with no pending hint is only re-checked this often, so scanning
# every enabled project each tick stays cheap even at fleet scale.
_BACKSTOP_INTERVAL_SECONDS = 5 * 60


@dataclass(frozen=True)
class _ScheduleEntry:
    failures: int
    next_attempt_at: datetime


@dataclass(frozen=True)
class _Target:
    project_key: str
    project_file: str | None
    primary_workspace_dir: str
    role: str
    hinted: bool

    @property
    def schedule_key(self) -> str:
        return f"{self.project_key}:{self.role}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _read_schedule_state(path: Path) -> dict[str, _ScheduleEntry]:
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}

    state: dict[str, _ScheduleEntry] = {}
    for key, raw_entry in payload.items():
        if not isinstance(key, str) or not isinstance(raw_entry, dict):
            continue
        failures = raw_entry.get("failures")
        next_attempt_at = _parse_datetime(raw_entry.get("next_attempt_at"))
        if (
            not isinstance(failures, int)
            or isinstance(failures, bool)
            or failures < 0
            or next_attempt_at is None
        ):
            continue
        state[key] = _ScheduleEntry(failures=failures, next_attempt_at=next_attempt_at)
    return state


def _write_schedule_state(path: Path, state: dict[str, _ScheduleEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        key: {
            "failures": entry.failures,
            "next_attempt_at": entry.next_attempt_at.isoformat(),
        }
        for key, entry in sorted(state.items())
    }
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def _persist_schedule_state(
    runtime: BuiltinChopRuntime,
    state_path: Path,
    state: dict[str, _ScheduleEntry],
) -> None:
    try:
        _write_schedule_state(state_path, state)
    except Exception as exc:  # noqa: BLE001 - state failure cannot fail the chop.
        runtime.log.warning(
            f"[sidecar_auto_sync] Failed to persist sync schedule state: {exc}"
        )


def _next_backoff_entry(
    previous: _ScheduleEntry | None, *, now: datetime
) -> _ScheduleEntry:
    failures = (previous.failures if previous is not None else 0) + 1
    exponent = min(failures, 5)
    delay_seconds = min(
        _BACKSTOP_INTERVAL_SECONDS * (2**exponent),
        _MAX_BACKOFF_SECONDS,
    )
    return _ScheduleEntry(
        failures=failures,
        next_attempt_at=now + timedelta(seconds=delay_seconds),
    )


def _next_backstop_entry(*, now: datetime) -> _ScheduleEntry:
    return _ScheduleEntry(
        failures=0,
        next_attempt_at=now + timedelta(seconds=_BACKSTOP_INTERVAL_SECONDS),
    )


def _enabled_project_records() -> list[ProjectRecordWire]:
    return [
        record
        for record in list_project_records(
            sase_projects_dir(),
            include_states=("enabled",),
            include_home=False,
            projects_only=True,
        )
        if record.is_project and record.workspace_dir
    ]


def _targets_for_project(
    runtime: BuiltinChopRuntime,
    record: ProjectRecordWire,
) -> list[_Target]:
    primary = record.workspace_dir
    assert primary is not None
    try:
        roles = auto_sync_roles(primary)
    except Exception as exc:  # noqa: BLE001 - one broken project cannot stall the rest.
        runtime.log.warning(
            f"[sidecar_auto_sync] Failed to resolve auto_sync roles for "
            f"{record.project_name}: {exc}"
        )
        return []
    if not roles:
        return []
    hinted = set(pending_sidecar_sync_roles(record.project_name))
    return [
        _Target(
            project_key=record.project_name,
            project_file=record.project_file,
            primary_workspace_dir=primary,
            role=role,
            hinted=role in hinted,
        )
        for role in roles
    ]


def _summary(
    runtime: BuiltinChopRuntime,
    *,
    targets: int,
    refreshed: int = 0,
    up_to_date: int = 0,
    missing: int = 0,
    skipped: int = 0,
    failed: int = 0,
    backed_off: int = 0,
    deferred: int = 0,
    reason: str | None = None,
) -> ChopResultBuilder:
    return runtime.emit_summary(
        {
            "targets": targets,
            "refreshed": refreshed,
            "up_to_date": up_to_date,
            "missing": missing,
            "skipped": skipped,
            "failed": failed,
            "backed_off": backed_off,
            "deferred": deferred,
        },
        reason=reason,
    )


@builtin_chop("sidecar_auto_sync")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    records = _enabled_project_records()
    targets: list[_Target] = []
    for record in records:
        targets.extend(_targets_for_project(runtime, record))

    if not targets:
        return _summary(runtime, targets=0, reason="no_auto_sync_roles")

    now = _utc_now()
    state_path = Path(runtime.context.state_dir) / _BACKOFF_STATE_FILENAME
    schedule_state = _read_schedule_state(state_path)
    live_keys = {target.schedule_key for target in targets}
    stale_keys = [key for key in schedule_state if key not in live_keys]
    for stale_key in stale_keys:
        del schedule_state[stale_key]
    if stale_keys:
        _persist_schedule_state(runtime, state_path, schedule_state)

    work_deadline = time.monotonic() + _WORK_BUDGET_SECONDS
    refreshed = up_to_date = missing = skipped = failed = backed_off = deferred = 0

    for target in sorted(targets, key=lambda item: item.schedule_key):
        entry = schedule_state.get(target.schedule_key)
        if not target.hinted and entry is not None and now < entry.next_attempt_at:
            backed_off += 1
            continue

        if time.monotonic() >= work_deadline:
            deferred += 1
            continue

        result: SidecarSyncResult = sync_primary_sidecar_role(
            target.project_key,
            target.role,
            project_file=target.project_file,
        )

        if target.hinted:
            clear_sidecar_sync_hint(target.project_key, target.role)

        if result.skipped:
            schedule_state[target.schedule_key] = _next_backoff_entry(entry, now=now)
            failed += 1
        else:
            schedule_state[target.schedule_key] = _next_backstop_entry(now=now)
            if result.status == "refreshed":
                refreshed += 1
            elif result.status == "up_to_date":
                up_to_date += 1
            elif result.status == "missing":
                missing += 1
            else:
                skipped += 1
        _persist_schedule_state(runtime, state_path, schedule_state)

    reason = None
    if refreshed == 0:
        if failed:
            reason = "sync_failed"
        elif backed_off and not (up_to_date or missing or skipped):
            reason = "all_backed_off"
        elif deferred:
            reason = "budget_exhausted"

    return _summary(
        runtime,
        targets=len(targets),
        refreshed=refreshed,
        up_to_date=up_to_date,
        missing=missing,
        skipped=skipped,
        failed=failed,
        backed_off=backed_off,
        deferred=deferred,
        reason=reason,
    )


def main() -> None:
    run_builtin_chop("sidecar_auto_sync")


if __name__ == "__main__":
    main()
