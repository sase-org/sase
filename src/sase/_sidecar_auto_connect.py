"""Connect-only first-use SDD sidecar connection for registered projects.

This is the ``sidecar_auto_sync`` chop's connect leg. A project's SDD
sidecars get connected on a machine in only two ways: ``sase repo init``, or
the project's first agent launch there. A project registered with ``sase
project add`` (or a hand-written spec, or a re-enable) that has not launched
yet stays unconnected. Artifact-run retention then fails closed, because the
project's beads and plans sidecars are required protection sources.

This leg closes that gap with the same connect-only ``auto_connect_sdd_store``
step that first launch runs. It clones sidecars that already exist remotely
and writes the primary's ``.sase/sdd-store.json``. It never creates a remote
repository. Individual missing role clones of an already-connected project are
out of scope here; the role-target pass only reports them.

The leg stays cheap on the chop's 30-second cadence:

- A connected project costs one cached stat and no network work.
- At most one project is connected (or fails to connect) per tick.
- A connect only starts while ``CONNECT_MIN_REMAINING_SECONDS`` of the chop's
  work budget remain; otherwise the project counts as deferred.
- Per-project schedule entries live in the chop's shared schedule state under
  ``<project>:__connect__``: a raised connect backs off exponentially, and a
  not-applicable project (unmanaged, or not remote-backed) is rechecked at the
  backstop interval.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, MutableMapping
import contextlib
from dataclasses import dataclass
from datetime import datetime
import io
from pathlib import Path
import time
from typing import Literal, Protocol

from sase.chops.sdk import ChopLogger
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.sdd.store import auto_connect_sdd_store, sdd_store_connected

__all__ = [
    "CONNECT_MIN_REMAINING_SECONDS",
    "ConnectLegResult",
    "run_connect_leg",
]

#: A connect clones whole sidecar repositories, so it only starts while this
#: much of the chop's work budget remains.
CONNECT_MIN_REMAINING_SECONDS = 60.0
_CONNECT_SCHEDULE_SUFFIX = ":__connect__"

_ConnectStatus = Literal["connected", "not_applicable", "failed"]


class _ScheduledEntry(Protocol):
    @property
    def next_attempt_at(self) -> datetime: ...


@dataclass(frozen=True)
class ConnectLegResult:
    """Counts and schedule bookkeeping from one connect-leg pass."""

    connected: int = 0
    failed: int = 0
    deferred: int = 0
    #: Schedule keys of projects that are still unconnected after this pass.
    #: The chop keeps these entries through its stale-key prune.
    pending_keys: frozenset[str] = frozenset()
    #: Whether this pass changed the shared schedule state.
    state_changed: bool = False


def _connect_schedule_key(project_key: str) -> str:
    """Return the schedule-state key for *project_key*'s connect attempts."""

    return f"{project_key}{_CONNECT_SCHEDULE_SUFFIX}"


def _unconnected_candidates(
    records: Iterable[ProjectRecordWire],
) -> list[tuple[str, str]]:
    """Return ``(project_key, primary)`` for each unconnected project.

    Sorted by project key so the order is deterministic. A project whose
    primary checkout is missing, or whose store record cannot be read, is not
    a candidate: connecting would fail the same way every time.
    """

    candidates: dict[str, str] = {}
    for record in records:
        primary = record.workspace_dir
        if not primary or record.project_name in candidates:
            continue
        if not Path(primary).expanduser().is_dir():
            continue
        if sdd_store_connected(primary) is False:
            candidates[record.project_name] = primary
    return sorted(candidates.items())


def _forward_captured_stderr(
    log: ChopLogger, project_key: str, captured: io.StringIO
) -> None:
    for line in captured.getvalue().splitlines():
        if line.strip():
            log.warning(f"[sidecar_auto_sync] Connect {project_key}: {line.strip()}")


def _connect_project(log: ChopLogger, project_key: str, primary: str) -> _ConnectStatus:
    """Run the first-launch connect step for one project, logging the outcome."""

    # auto_connect_sdd_store prints its missing-agents-sidecar warning to
    # stderr; route it into the chop log instead of unstructured output.
    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            # Workspace 1 is the primary, as in auto_connect_sdd_store's own
            # internal calls.
            connected = auto_connect_sdd_store(primary, 1)
    except Exception as exc:  # noqa: BLE001 - one project never stalls the chop.
        _forward_captured_stderr(log, project_key, captured)
        log.warning(
            f"[sidecar_auto_sync] Failed to connect SDD sidecars for "
            f"{project_key}: {exc}"
        )
        return "failed"
    _forward_captured_stderr(log, project_key, captured)
    if not connected:
        return "not_applicable"
    log.info(f"[sidecar_auto_sync] Connected existing SDD sidecars for {project_key}")
    return "connected"


def run_connect_leg[EntryT: _ScheduledEntry](
    records: Iterable[ProjectRecordWire],
    *,
    schedule_state: MutableMapping[str, EntryT],
    now: datetime,
    work_deadline: float,
    backoff_entry: Callable[[EntryT | None], EntryT],
    backstop_entry: Callable[[], EntryT],
    log: ChopLogger,
) -> ConnectLegResult:
    """Connect at most one enabled-but-unconnected project's SDD sidecars.

    ``schedule_state`` is the chop's shared schedule mapping, updated in
    place. ``backoff_entry`` and ``backstop_entry`` build its next entries.
    Not-applicable projects are cheap no-ops (no network), so they do not use
    up the tick's single connect; a connect that succeeds or raises ends the
    pass.
    """

    candidates = _unconnected_candidates(records)
    pending = {_connect_schedule_key(project_key) for project_key, _ in candidates}
    connected = failed = deferred = 0
    state_changed = False

    for project_key, primary in candidates:
        key = _connect_schedule_key(project_key)
        entry = schedule_state.get(key)
        if entry is not None and now < entry.next_attempt_at:
            continue
        if work_deadline - time.monotonic() < CONNECT_MIN_REMAINING_SECONDS:
            deferred += 1
            break

        status = _connect_project(log, project_key, primary)
        state_changed = True
        if status == "connected":
            connected += 1
            schedule_state.pop(key, None)
            pending.discard(key)
            break
        if status == "failed":
            failed += 1
            schedule_state[key] = backoff_entry(entry)
            break
        schedule_state[key] = backstop_entry()

    return ConnectLegResult(
        connected=connected,
        failed=failed,
        deferred=deferred,
        pending_keys=frozenset(pending),
        state_changed=state_changed,
    )
