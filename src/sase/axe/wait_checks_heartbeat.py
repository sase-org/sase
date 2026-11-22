"""Heartbeat the ``wait_checks`` chop stamps after every completed run.

``wait_checks`` writes ``ready.json`` for parked runners. A lean waiter
(``run_agent_lean_wait.py``) trusts that chop while its heartbeat is fresh and
falls back to resolving its own dependencies when the heartbeat goes stale, so
a ``wait_checks`` outage cannot strand a parked runner. The heartbeat is the
epoch of the last completed run as text; the waiter reads it with the standard
library only.

The chop runs at least every 120 s through ``max_quiet`` while the scheduler is
alive, so a heartbeat older than a few minutes means the chop is not running.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from sase.core.paths import sase_home

HEARTBEAT_FILE_NAME = "wait_checks_heartbeat"


# symvision: tools/lean_wait_harness
def wait_checks_heartbeat_path() -> Path:
    """Return the heartbeat stamp path under the SASE state root."""
    return sase_home() / "axe" / HEARTBEAT_FILE_NAME


def stamp_wait_checks_heartbeat() -> None:
    """Record that a ``wait_checks`` run just completed (best effort, never raises)."""
    try:
        path = wait_checks_heartbeat_path()
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            tmp_path.write_text(f"{time.time()}\n", encoding="utf-8")
            tmp_path.replace(path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
    except Exception:  # noqa: BLE001 - a heartbeat failure must never fail the chop.
        pass


__all__ = [
    "HEARTBEAT_FILE_NAME",
    "stamp_wait_checks_heartbeat",
    "wait_checks_heartbeat_path",
]
