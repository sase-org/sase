"""Shared helpers for hijack recover-reconcile tests.

Split from ``tests.test_agent_hijack_recover_reconcile``. Helpers use public
names so focused test modules can import them without touching a ``_``-prefixed
symbol across files.
"""

from __future__ import annotations

import time
from typing import Any

from sase.agent.hijack.recover_reconcile import ReconcileDeps


def resolving_record(**overrides: Any) -> dict[str, Any]:
    """Return a resolving hijack ledger record for reconcile tests."""
    base = {
        "schema_version": 1,
        "hijack_id": "h-1",
        "agent_name": "acme--3",
        "artifacts_dir": "/tmp/pre",
        "session": "acme",
        "project_file": "/tmp/proj.sase",
        "workspace_num": 3,
        "workspace_dir": "/ws/3",
        "state": "resolving",
        "revision": 4,
        "resolution_action": "escalate",
        "reserved_successor_name": "acme--4",
        "concrete_target_model": "claude/opus@xhigh",
        "model_changed": True,
        "resolver_pid": 99999999,
        "resolver_process_identity_token": "boot:111",
        "updated_at": "2020-01-01T00:00:00+00:00",
        "hijacked_at": "2020-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def dead_seams(**overrides: Any) -> ReconcileDeps:
    """Return reconcile seams whose resolver process is already gone."""
    kwargs: dict[str, Any] = {
        "is_process_running": lambda pid: False,
        "process_identity_token": lambda pid: "boot:999",
        "observe_admission": lambda request_id: {
            "request_id": request_id,
            "state": "missing",
        },
        "load_successor_artifacts": lambda record: None,
        "now_unix": lambda: time.time(),
    }
    kwargs.update(overrides)
    return ReconcileDeps(**kwargs)
