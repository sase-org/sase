"""Best-effort ACE-side durable proc reconciliation."""

from __future__ import annotations

import logging

from sase.core.state_write_guard import pytest_path_is_sandboxed
from sase.procs import Proc, proc_store_path, reconcile_running_procs

log = logging.getLogger(__name__)


def reconcile_running_procs_safely() -> list[Proc]:
    """Terminalize orphaned active proc rows without letting errors escape."""
    if not pytest_path_is_sandboxed(proc_store_path()):
        return []
    try:
        return reconcile_running_procs()
    except Exception:
        log.debug("ACE proc reconciliation failed", exc_info=True)
        return []


__all__ = ["reconcile_running_procs_safely"]
