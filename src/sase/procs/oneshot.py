"""Transient oneshot service procs: the durable store behind ``!`` commands.

A oneshot is one durable proc row whose wire ``service`` block is
``{mode: oneshot, source: transient}``. It runs detached under its own proc
supervisor (outside the service host's process tree), records its exit code
on the row, and is never restarted or replayed. The TUI's ``!`` background
commands and ``sase service proc run`` share :func:`submit_oneshot`.

Oneshots keep the ``#1``-``#9`` display indices of the retired slot
directories: each carries a ``bgcmd-slot:<n>`` concurrency key, so the store
refuses a second *active* oneshot on the same index (within one project; see
:func:`oneshot_display_rows` for the cross-project case). Only active
oneshots consume an index; a finished command never blocks a new one, and a
finished row's index is reused (newest row wins) once all nine are taken.
"""

from __future__ import annotations

import shlex
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Final

from .models import ACTIVE_PROC_STATUSES, Proc
from .request import ProcSubmitRequest
from .runner import ProcSubmitError, submit_proc_request
from .service_meta import (
    SERVICE_ONESHOT_ORIGIN,
    SERVICE_PROC_MODE_ONESHOT,
    SERVICE_PROC_SOURCE_TRANSIENT,
    ProcServiceBlock,
)
from .store import read_procs

ONESHOT_ORIGIN: Final = SERVICE_ONESHOT_ORIGIN
ONESHOT_SLOT_KEY_PREFIX: Final = "bgcmd-slot:"
MAX_ONESHOT_SLOTS: Final = 9

_SHELL_ARGV_PREFIX: Final = ("sh", "-c")


class _OneshotSlotsExhaustedError(ProcSubmitError):
    """Every ``#1``-``#9`` oneshot index is held by an active oneshot."""


def _oneshot_slot_key(slot: int) -> str:
    """Return the concurrency key that reserves display index *slot*."""
    return f"{ONESHOT_SLOT_KEY_PREFIX}{slot}"


def _oneshot_service_block() -> ProcServiceBlock:
    """Return the ``service`` marker every transient oneshot row carries."""
    return ProcServiceBlock(
        name=None,
        mode=SERVICE_PROC_MODE_ONESHOT,
        source=SERVICE_PROC_SOURCE_TRANSIENT,
    )


def _is_transient_oneshot(proc: Proc) -> bool:
    """Return whether *proc* is a transient oneshot service proc row."""
    service = proc.service
    return (
        service is not None
        and service.mode == SERVICE_PROC_MODE_ONESHOT
        and service.source == SERVICE_PROC_SOURCE_TRANSIENT
    )


def _oneshot_slot(proc: Proc) -> int | None:
    """Return the ``#n`` display index a oneshot row reserved, if any."""
    for key in proc.concurrency_keys:
        if not key.startswith(ONESHOT_SLOT_KEY_PREFIX):
            continue
        try:
            slot = int(key[len(ONESHOT_SLOT_KEY_PREFIX) :])
        except ValueError:
            continue
        if 1 <= slot <= MAX_ONESHOT_SLOTS:
            return slot
    return None


def _oneshot_is_active(proc: Proc) -> bool:
    """Return whether *proc* is still pending, running, or settling."""
    return proc.status in ACTIVE_PROC_STATUSES


def oneshot_command_text(proc: Proc) -> str:
    """Return the shell command a oneshot ran, as the user typed it."""
    argv = list(proc.argv or proc.command)
    if len(argv) == 3 and tuple(argv[:2]) == _SHELL_ARGV_PREFIX:
        return argv[2]
    return shlex.join(argv)


def oneshot_shell_argv(command: str) -> list[str]:
    """Return the argv that runs the shell *command* string."""
    return [*_SHELL_ARGV_PREFIX, command]


def oneshot_display_rows(
    procs: Iterable[Proc], *, dismissed: Collection[str] = ()
) -> dict[int, Proc]:
    """Map each ``#n`` index to the row that currently owns it.

    *procs* is newest-first (the store's read order). An active row always
    keeps its index; a finished row shows only while it is the newest finished
    row on its index and has not been dismissed, so an older finished row is
    never resurrected by a newer one's dismissal.

    The store fences ``bgcmd-slot:<n>`` per project, so two active oneshots
    from different projects can (rarely) hold the same index. The older one is
    re-homed to the lowest free index instead of vanishing.
    """
    rows: dict[int, Proc] = {}
    overflow: list[Proc] = []
    latest_finished: dict[int, Proc] = {}
    for proc in procs:
        if not _is_transient_oneshot(proc):
            continue
        slot = _oneshot_slot(proc)
        if slot is None:
            continue
        if _oneshot_is_active(proc):
            if slot in rows:
                overflow.append(proc)
            else:
                rows[slot] = proc
        else:
            latest_finished.setdefault(slot, proc)
    for slot, proc in latest_finished.items():
        if slot not in rows and proc.proc_id not in dismissed:
            rows[slot] = proc
    for proc in reversed(overflow):
        free = next((n for n in range(1, MAX_ONESHOT_SLOTS + 1) if n not in rows), None)
        if free is not None:
            rows[free] = proc
    return rows


def choose_oneshot_slot(
    occupancy: Mapping[int, tuple[bool, str]],
    *,
    reserved: Collection[int] = (),
) -> int | None:
    """Pick the ``#n`` index for a new oneshot, or ``None`` when all are active.

    *occupancy* maps an index to ``(is_active, sort_key)`` for every visible
    row; *reserved* holds indices that must not be reused (launches still in
    flight, legacy slot directories). The lowest free index wins; when none
    is free the index of the oldest finished row is reused.
    """
    blocked = set(reserved)
    for slot in range(1, MAX_ONESHOT_SLOTS + 1):
        if slot not in occupancy and slot not in blocked:
            return slot
    finished = [
        (sort_key, slot)
        for slot, (active, sort_key) in occupancy.items()
        if not active and slot not in blocked
    ]
    if not finished:
        return None
    return min(finished)[1]


def _proc_occupancy(rows: Mapping[int, Proc]) -> dict[int, tuple[bool, str]]:
    """Return :func:`choose_oneshot_slot` occupancy for oneshot *rows*."""
    return {
        slot: (
            _oneshot_is_active(proc),
            proc.finished_at or proc.started_at or proc.created_at,
        )
        for slot, proc in rows.items()
    }


def submit_oneshot(
    argv: Sequence[str],
    *,
    label: str,
    cwd: str | Path,
    project: str | None = None,
    workspace_num: int | None = None,
    cl_name: str | None = None,
    slot: int | None = None,
    session_id: str | None = None,
) -> Proc:
    """Submit *argv* as a detached transient oneshot service proc.

    The single code path behind ``!`` background commands and
    ``sase service proc run``. With no *slot* the lowest free ``#n`` index is
    chosen; :class:`_OneshotSlotsExhaustedError` is raised when nine oneshots
    are already active. A concurrent submit that wins the same index is
    refused by the store with a concurrency :class:`ProcSubmitError`.
    """
    if slot is None:
        slot = _choose_store_slot()
    return submit_proc_request(
        ProcSubmitRequest(
            argv=list(argv),
            label=label,
            cwd=cwd,
            origin=ONESHOT_ORIGIN,
            project=project,
            workspace_num=workspace_num,
            cl_name=cl_name,
            session_id=session_id,
            concurrency_keys=(_oneshot_slot_key(slot),),
            service=_oneshot_service_block(),
        )
    )


def _choose_store_slot() -> int:
    from sase.ace.dismissed_proc_shells import load_dismissed_proc_shells

    rows = oneshot_display_rows(read_procs(), dismissed=load_dismissed_proc_shells())
    slot = choose_oneshot_slot(_proc_occupancy(rows))
    if slot is None:
        raise _OneshotSlotsExhaustedError(
            f"all {MAX_ONESHOT_SLOTS} oneshot slots are running; wait for one "
            "to finish or stop one first"
        )
    return slot


__all__ = [
    "MAX_ONESHOT_SLOTS",
    "ONESHOT_ORIGIN",
    "ONESHOT_SLOT_KEY_PREFIX",
    "choose_oneshot_slot",
    "oneshot_command_text",
    "oneshot_display_rows",
    "oneshot_shell_argv",
    "submit_oneshot",
]
