"""Per-process faulthandler spools for the ACE TUI.

``faulthandler`` writes only when a fatal signal kills the process, so a
session header at every start turned ``tui_faults.log`` into a list of
launches. Instead, each TUI process points faulthandler at its own headerless
spool, ``tui_faults.d/<pid>-<start_ms>-<version>.log``. A clean exit closes
the spool and deletes it when empty. At the next start, every spool whose
process is gone is harvested: non-empty spools are appended to
``tui_faults.log`` under a ``[<start>] pid=<pid> sase=<version>`` header,
then every dead spool is deleted.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from sase.logs._bounded import DEFAULT_MAX_BYTES, append_bytes_locked, log_file_lock

log = logging.getLogger(__name__)

FAULT_LOG_NAME = "tui_faults.log"
SPOOL_DIR_NAME = "tui_faults.d"
_SPOOL_NAME_RE = re.compile(r"^(?P<pid>\d+)-(?P<start_ms>\d+)-(?P<version>[^/]*)\.log$")
_UNSAFE_VERSION_CHARS = re.compile(r"[^A-Za-z0-9._+]")


@dataclass
class TuiFaultSpool:
    """One process's open faulthandler spool file."""

    path: Path
    file: TextIO


def open_tui_fault_spool(
    logs_dir: Path,
    *,
    version: str,
    pid: int | None = None,
    start_time: float | None = None,
) -> TuiFaultSpool:
    """Create and open this process's headerless faulthandler spool."""
    spool_dir = logs_dir / SPOOL_DIR_NAME
    spool_dir.mkdir(parents=True, exist_ok=True)
    pid = os.getpid() if pid is None else pid
    start_ms = int((time.time() if start_time is None else start_time) * 1000)
    safe_version = _UNSAFE_VERSION_CHARS.sub("_", version) or "unknown"
    path = spool_dir / f"{pid}-{start_ms}-{safe_version}.log"
    return TuiFaultSpool(path=path, file=path.open("a", encoding="utf-8"))


def close_tui_fault_spool(spool: TuiFaultSpool) -> None:
    """Close *spool* and delete it when faulthandler never wrote to it."""
    try:
        spool.file.close()
    except OSError:
        log.debug("could not close TUI fault spool %s", spool.path, exc_info=True)
    try:
        if spool.path.stat().st_size == 0:
            spool.path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        log.debug("could not remove TUI fault spool %s", spool.path, exc_info=True)


def harvest_tui_fault_spools(logs_dir: Path) -> int:
    """Move dead processes' fault spools into ``tui_faults.log``.

    Returns how many non-empty spools were appended. Spools of live processes
    are left alone. A spool carrying this process's own pid was written by an
    earlier ``exec`` image (TUI restarts re-exec in place), so it counts as
    dead; call this before opening this process's own spool. Harvesting runs
    under the fault log's sibling lock, so concurrent TUI starts never append
    the same spool twice.
    """
    spool_dir = logs_dir / SPOOL_DIR_NAME
    try:
        candidates = sorted(spool_dir.iterdir())
    except FileNotFoundError:
        return 0
    dead: list[tuple[int, Path, re.Match[str]]] = []
    for path in candidates:
        match = _SPOOL_NAME_RE.match(path.name)
        if match is None:
            continue
        pid = int(match["pid"])
        if not _spool_owner_alive(pid):
            dead.append((int(match["start_ms"]), path, match))
    if not dead:
        return 0
    fault_log = logs_dir / FAULT_LOG_NAME
    harvested = 0
    with log_file_lock(fault_log):
        for _, path, match in sorted(dead, key=lambda item: item[0]):
            try:
                content = path.read_bytes()
            except FileNotFoundError:
                continue
            if content.strip():
                append_bytes_locked(
                    fault_log,
                    _fault_header(match) + content + _trailing_newline(content),
                    max_bytes=DEFAULT_MAX_BYTES,
                )
                harvested += 1
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    return harvested


def _fault_header(match: re.Match[str]) -> bytes:
    started = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(match["start_ms"]) / 1000)
    )
    return f"\n[{started}] pid={match['pid']} sase={match['version']}\n".encode()


def _trailing_newline(content: bytes) -> bytes:
    return b"" if content.endswith(b"\n") else b"\n"


def _spool_owner_alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


__all__ = [
    "FAULT_LOG_NAME",
    "SPOOL_DIR_NAME",
    "TuiFaultSpool",
    "close_tui_fault_spool",
    "harvest_tui_fault_spools",
    "open_tui_fault_spool",
]
