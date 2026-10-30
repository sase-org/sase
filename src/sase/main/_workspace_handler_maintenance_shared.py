"""Shared helpers for ``sase workspace`` maintenance commands."""

from __future__ import annotations

import os
from collections.abc import Callable

from sase.workspace_provider.occupant import read_occupant_record

ClaimedNums = Callable[[str], set[int]]


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
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


def has_live_occupant(checkout_dir: str) -> bool:
    record = read_occupant_record(checkout_dir)
    return record is not None and _pid_is_alive(record.pid)
