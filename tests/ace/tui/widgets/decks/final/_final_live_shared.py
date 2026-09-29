"""Shared helpers for final live-tail tests.

Public helpers used by more than one ``test_final_live_*`` module
live here under public names so no new module imports a ``_``-prefixed
name from another new module.
"""

from __future__ import annotations

from sase.core.finalizer_run_view import (
    _RunViewAttempt,
    _RunViewOperation,
    RunViewRun,
    RunViewRunInstance,
)

__all__ = [
    "NOW",
    "make_active_op",
    "make_run",
    "make_run_instance",
]

NOW = 1_800_000_000.0


def make_active_op(**kwargs: object) -> _RunViewOperation:
    base: dict[str, object] = {
        "op": "just check",
        "kind": "subprocess",
        "label": "just check",
        "attempt": 1,
        "started_at": NOW - 30.0,
        "returncode": None,
        "live_tail": ["line one", "line two"],
    }
    base.update(kwargs)
    return _RunViewOperation(**base)  # type: ignore[arg-type]


def make_run_instance(op: _RunViewOperation, **kwargs: object) -> RunViewRunInstance:
    base: dict[str, object] = {
        "instance_id": "check",
        "status": "running",
        "attempts": [_RunViewAttempt(attempt=1, status="running")],
        "operations": [op],
        "attempt": 1,
        "max_attempts": 1,
        "op": "just check",
    }
    base.update(kwargs)
    return RunViewRunInstance(**base)  # type: ignore[arg-type]


def make_run(run_id: str, item: RunViewRunInstance, **kwargs: object) -> RunViewRun:
    base: dict[str, object] = {
        "run_id": run_id,
        "number": 0,
        "label": run_id,
        "kind": "agent",
        "disposition": "active",
        "instances": [item],
    }
    base.update(kwargs)
    return RunViewRun(**base)  # type: ignore[arg-type]
