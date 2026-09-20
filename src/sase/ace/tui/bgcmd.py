"""Background command state for sase's TUI.

``!`` background commands are transient oneshot service procs: each one is a
durable row in the proc store (``service = {mode: oneshot, source:
transient}``) with a recorded exit code, a store-owned log, and a stable
``#1``-``#9`` display index (its ``bgcmd-slot:<n>`` concurrency key). This
module turns those rows into the slot-keyed :class:`BackgroundCommandInfo`
records the Services tab renders.

Slot directories under ``~/.sase/axe/bgcmd/`` are the retired storage. While
the ``bgcmd_legacy_slots`` sunset flag is on they stay readable (and can be
stopped, cleared, and dismissed) until they age out; nothing ever writes a new
one. Every reader here does disk I/O: call them off the event loop.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
from collections import deque
from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.paths import sase_subdir
from sase.core.time import get_timezone
from sase.project_display_names import project_display_name_for

if TYPE_CHECKING:
    from sase.procs.models import Proc

# Retired slot-directory storage (read-only behind ``bgcmd_legacy_slots``).
BGCMD_STATE_DIR = sase_subdir("axe") / "bgcmd"

# Number of ``#n`` display indices (1-9).
MAX_SLOTS = 9

_ACTIVE_STATUSES = frozenset({"pending", "running", "settling"})
_LEGACY_INFO_FIELDS = ("command", "project", "workspace_num", "workspace_dir")


@dataclass
class BackgroundCommandInfo:
    """One background command: a durable oneshot row or a legacy slot dir."""

    command: str
    project: str
    workspace_num: int
    workspace_dir: str
    started_at: str
    pid: int | None = None
    finished_at: str | None = None  # Set when command completes
    project_display_name: str | None = field(default=None, compare=False)
    # Set for durable oneshot rows; ``None`` marks a legacy slot directory.
    proc_id: str | None = None
    # A proc status (``pending``/``running``/``settling``/``success``/
    # ``error``/``killed``); legacy directories report ``running`` or ``done``.
    status: str = "running"
    exit_code: int | None = None
    log_path: str | None = None

    @property
    def display_project(self) -> str:
        """User-facing project label for display-only surfaces."""
        return self.project_display_name or self.project

    @property
    def running(self) -> bool:
        """Whether the command is still pending, running, or settling."""
        return self.status in _ACTIVE_STATUSES

    @property
    def legacy(self) -> bool:
        """Whether this record is a retired slot directory, not a proc row."""
        return self.proc_id is None


def bgcmd_identity(slot: int, info: BackgroundCommandInfo) -> str:
    """Return the stable identity a dismissal is keyed by."""
    return info.proc_id or f"legacy:{slot}"


def _legacy_slots_enabled() -> bool:
    """Whether retired slot directories are still read (sunset flag)."""
    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.bgcmd_legacy_slots)


# --- Durable oneshot rows ------------------------------------------------


def _info_from_proc(proc: Proc) -> BackgroundCommandInfo:
    from sase.procs.oneshot import oneshot_command_text

    project = proc.project or ""
    return BackgroundCommandInfo(
        command=oneshot_command_text(proc),
        project=project,
        workspace_num=proc.workspace_num or 0,
        workspace_dir=proc.cwd,
        started_at=proc.started_at or proc.created_at,
        pid=proc.pid,
        finished_at=None if proc.status in _ACTIVE_STATUSES else proc.finished_at,
        project_display_name=project_display_name_for(project) if project else None,
        proc_id=proc.proc_id,
        status=proc.status,
        exit_code=proc.exit_code,
        log_path=proc.log_path,
    )


def _read_oneshot_infos() -> dict[int, BackgroundCommandInfo]:
    from sase.ace.dismissed_proc_shells import load_dismissed_proc_shells
    from sase.procs import read_procs
    from sase.procs.oneshot import oneshot_display_rows

    rows = oneshot_display_rows(read_procs(), dismissed=load_dismissed_proc_shells())
    return {slot: _info_from_proc(proc) for slot, proc in rows.items()}


# --- Legacy slot directories ---------------------------------------------


def _slot_dir(slot: int) -> Path:
    return BGCMD_STATE_DIR / str(slot)


def _read_legacy_pid(slot: int) -> int | None:
    try:
        return int((_slot_dir(slot) / "pid").read_text().strip())
    except (ValueError, OSError):
        return None


def _is_process_running(pid: int) -> bool:
    """Check if a process is running (not a zombie)."""
    try:
        # Try to reap zombie if it's our child process
        result, _ = os.waitpid(pid, os.WNOHANG)
        if result == pid:
            return False
    except ChildProcessError:
        # Not our child, can't waitpid on it - fall through to kill check
        pass
    except OSError:
        return False

    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_legacy_info(slot: int) -> BackgroundCommandInfo | None:
    info_file = _slot_dir(slot) / "info.json"
    try:
        with open(info_file) as f:
            data = json.load(f)
        info = BackgroundCommandInfo(**data)
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    info.project_display_name = project_display_name_for(info.project)
    pid = _read_legacy_pid(slot)
    running = pid is not None and _is_process_running(pid)
    info.status = "running" if running else "done"
    if not running and info.finished_at is None:
        _mark_legacy_finished(slot, info)
    return info


def _mark_legacy_finished(slot: int, info: BackgroundCommandInfo) -> None:
    info.finished_at = datetime.now(get_timezone()).isoformat()
    data = {
        key: value
        for key, value in asdict(info).items()
        if key in (*_LEGACY_INFO_FIELDS, "started_at", "pid", "finished_at")
    }
    try:
        with open(_slot_dir(slot) / "info.json", "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def _read_legacy_infos() -> dict[int, BackgroundCommandInfo]:
    infos: dict[int, BackgroundCommandInfo] = {}
    for slot in range(1, MAX_SLOTS + 1):
        info = _read_legacy_info(slot)
        if info is not None:
            infos[slot] = info
    return infos


def _tail_lines(path: Path, lines: int) -> str:
    try:
        with open(path) as f:
            return "".join(deque(f, maxlen=lines))
    except OSError:
        return ""


# --- Public reads ---------------------------------------------------------


def read_bgcmd_slots() -> dict[int, BackgroundCommandInfo]:
    """Return every visible background command keyed by its ``#n`` index.

    One proc-store read, plus a scan of the retired slot directories while
    ``bgcmd_legacy_slots`` is on. A durable row wins an index a legacy
    directory also holds.
    """
    infos: dict[int, BackgroundCommandInfo] = {}
    if _legacy_slots_enabled():
        infos.update(_read_legacy_infos())
    infos.update(_read_oneshot_infos())
    return infos


def get_slot_info(slot: int) -> BackgroundCommandInfo | None:
    """Return the command shown at ``#slot``, or ``None``."""
    return read_bgcmd_slots().get(slot)


def read_slot_output_tail(slot: int, lines: int = 500) -> str:
    """Return the last *lines* lines of the output at ``#slot``."""
    info = get_slot_info(slot)
    if info is None:
        return ""
    return read_info_output_tail(slot, info, lines)


def read_info_output_tail(
    slot: int, info: BackgroundCommandInfo, lines: int = 500
) -> str:
    """Return the tail of *info*'s output, whichever storage backs it."""
    if info.proc_id is None:
        return _tail_lines(_slot_dir(slot) / "output.log", lines)
    from sase.procs import read_proc_log_tail

    return read_proc_log_tail(info.proc_id, lines, log_path=info.log_path)


def clear_slot_output(slot: int, info: BackgroundCommandInfo) -> None:
    """Truncate the output *info* shows at ``#slot``."""
    if info.legacy:
        paths = [_slot_dir(slot) / "output.log"]
    elif info.log_path:
        log = Path(info.log_path)
        paths = [log, log.with_name(f"{log.name}.1")]
    else:
        return
    for path in paths:
        if path.exists():
            try:
                path.write_text("")
            except OSError:
                pass


# --- Slot allocation ------------------------------------------------------


def choose_bgcmd_slot(
    infos: Mapping[int, BackgroundCommandInfo],
    *,
    reserved: Collection[int] = (),
) -> int | None:
    """Pick the ``#n`` index for a new background command.

    Only *running* commands hold an index: a finished one is reused (oldest
    first) once all nine indices are taken, so history never blocks a new
    command. A legacy slot directory is never reused until dismissed.
    *reserved* holds indices whose launch is still in flight.
    """
    from sase.procs.oneshot import choose_oneshot_slot

    legacy = {slot for slot, info in infos.items() if info.legacy}
    occupancy = {
        slot: (info.running, info.finished_at or info.started_at)
        for slot, info in infos.items()
        if not info.legacy
    }
    return choose_oneshot_slot(occupancy, reserved={*reserved, *legacy})


# --- Dismiss / stop for legacy directories --------------------------------


def dismiss_background_command(slot: int, info: BackgroundCommandInfo) -> bool:
    """Hide a finished command: drop its legacy dir or record the dismissal.

    Durable proc rows are never deleted; dismissal is host-side ACE state, so
    the run stays in ``sase proc list`` with its exit code.
    """
    if info.proc_id is not None:
        from sase.ace.dismissed_proc_shells import record_dismissed_proc_shells

        return record_dismissed_proc_shells([info.proc_id])
    slot_dir = _slot_dir(slot)
    if slot_dir.exists():
        shutil.rmtree(slot_dir, ignore_errors=True)
    return True


def stop_legacy_background_command(slot: int) -> bool:
    """SIGTERM a legacy slot directory's process group.

    Durable oneshots are stopped with ``sase proc kill`` instead.
    """
    pid = _read_legacy_pid(slot)
    if pid is None:
        return False
    try:
        if _is_process_running(pid):
            os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        (_slot_dir(slot) / "pid").unlink()
    except OSError:
        pass
    return True


__all__ = [
    "BGCMD_STATE_DIR",
    "MAX_SLOTS",
    "BackgroundCommandInfo",
    "bgcmd_identity",
    "choose_bgcmd_slot",
    "clear_slot_output",
    "dismiss_background_command",
    "get_slot_info",
    "read_bgcmd_slots",
    "read_info_output_tail",
    "read_slot_output_tail",
    "stop_legacy_background_command",
]
