#!/usr/bin/env python3
"""Refresh canonical bead stores for projects with live bead waiters."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sase.agent.names import is_process_alive
from sase.bead.store_locator import canonical_beads_dir_for_project
from sase.bead.sync import bead_refresh_mode, refresh_bead_store
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import sase_projects_dir

_RUN_EVERY_SECONDS = 30
_MAX_BACKOFF_SECONDS = 15 * 60
_BACKOFF_STATE_FILENAME = "bead_store_refresh_backoff.json"
_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    only_workflow_dirs=("ace-run",),
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    include_done_markers=False,
    include_workflow_state=False,
    include_waiting=True,
)


@dataclass(frozen=True)
class _BackoffEntry:
    failures: int
    next_attempt_at: datetime


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


def _read_backoff_state(path: Path) -> dict[str, _BackoffEntry]:
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}

    state: dict[str, _BackoffEntry] = {}
    for project_name, raw_entry in payload.items():
        if not isinstance(project_name, str) or not isinstance(raw_entry, dict):
            continue
        failures = raw_entry.get("failures")
        next_attempt_at = _parse_datetime(raw_entry.get("next_attempt_at"))
        if (
            not isinstance(failures, int)
            or isinstance(failures, bool)
            or failures < 1
            or next_attempt_at is None
        ):
            continue
        state[project_name] = _BackoffEntry(
            failures=failures,
            next_attempt_at=next_attempt_at,
        )
    return state


def _write_backoff_state(path: Path, state: dict[str, _BackoffEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        project_name: {
            "failures": entry.failures,
            "next_attempt_at": entry.next_attempt_at.isoformat(),
        }
        for project_name, entry in sorted(state.items())
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


def _waiting_agent_is_alive(record: AgentArtifactRecordWire) -> bool | None:
    meta: dict[str, object] = {}
    if record.agent_meta is not None:
        if record.agent_meta.pid is not None:
            meta["pid"] = record.agent_meta.pid
        if record.agent_meta.stopped_at is not None:
            meta["stopped_at"] = record.agent_meta.stopped_at
    try:
        return is_process_alive(meta, Path(record.artifact_dir))
    except Exception:  # noqa: BLE001 - uncertain liveness must fail open.
        return None


def _projects_with_live_bead_waits(projects_root: Path) -> set[str]:
    snapshot = scan_agent_artifacts(projects_root, _SCAN_OPTIONS)
    projects: set[str] = set()
    for record in snapshot.records:
        waiting = record.waiting
        artifact_dir = Path(record.artifact_dir)
        if (
            waiting is None
            or not waiting.wait_for_beads
            or (artifact_dir / "ready.json").exists()
        ):
            continue
        if _waiting_agent_is_alive(record) is False:
            continue
        projects.add(record.project_name)
    return projects


def _next_backoff_entry(
    previous: _BackoffEntry | None,
    *,
    now: datetime,
) -> _BackoffEntry:
    failures = (previous.failures if previous is not None else 0) + 1
    exponent = min(failures, 5)
    delay_seconds = min(
        _RUN_EVERY_SECONDS * (2**exponent),
        _MAX_BACKOFF_SECONDS,
    )
    return _BackoffEntry(
        failures=failures,
        next_attempt_at=now + timedelta(seconds=delay_seconds),
    )


def _summary(
    runtime: BuiltinChopRuntime,
    *,
    projects_waiting: int,
    stores_refreshed: int = 0,
    stores_failed: int = 0,
    stores_backed_off: int = 0,
    reason: str | None = None,
) -> ChopResultBuilder:
    return runtime.emit_summary(
        {
            "projects_waiting": projects_waiting,
            "stores_refreshed": stores_refreshed,
            "stores_failed": stores_failed,
            "stores_backed_off": stores_backed_off,
        },
        reason=reason,
    )


@builtin_chop("bead_store_refresh")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    if bead_refresh_mode() == "off":
        return _summary(
            runtime,
            projects_waiting=0,
            reason="bead_refresh_disabled",
        )

    projects = _projects_with_live_bead_waits(sase_projects_dir())
    if not projects:
        return _summary(runtime, projects_waiting=0, reason="no_bead_waits")

    now = _utc_now()
    state_path = Path(runtime.context.state_dir) / _BACKOFF_STATE_FILENAME
    backoff_state = _read_backoff_state(state_path)
    state_changed = False
    canonical_stores = 0
    stores_refreshed = 0
    stores_failed = 0
    stores_backed_off = 0

    for project_name in sorted(projects):
        entry = backoff_state.get(project_name)
        if entry is not None and now < entry.next_attempt_at:
            stores_backed_off += 1
            continue

        try:
            beads_dir = canonical_beads_dir_for_project(project_name)
            if beads_dir is None:
                continue
            canonical_stores += 1
            refresh_bead_store(beads_dir)
        except Exception as exc:  # noqa: BLE001 - refreshes are best effort.
            stores_failed += 1
            backoff_state[project_name] = _next_backoff_entry(entry, now=now)
            state_changed = True
            runtime.log.warning(
                f"[bead_store_refresh] Failed to refresh bead store for "
                f"{project_name}: {exc}"
            )
            continue

        stores_refreshed += 1
        if project_name in backoff_state:
            del backoff_state[project_name]
            state_changed = True

    if state_changed:
        try:
            _write_backoff_state(state_path, backoff_state)
        except Exception as exc:  # noqa: BLE001 - state failure cannot fail the chop.
            runtime.log.warning(
                f"[bead_store_refresh] Failed to persist refresh backoff state: {exc}"
            )

    reason = None
    if stores_refreshed == 0:
        if stores_failed:
            reason = "refresh_failed"
        elif stores_backed_off:
            reason = "all_backed_off"
        elif canonical_stores == 0:
            reason = "no_canonical_stores"

    return _summary(
        runtime,
        projects_waiting=len(projects),
        stores_refreshed=stores_refreshed,
        stores_failed=stores_failed,
        stores_backed_off=stores_backed_off,
        reason=reason,
    )


def main() -> None:
    run_builtin_chop("bead_store_refresh")


if __name__ == "__main__":
    main()
