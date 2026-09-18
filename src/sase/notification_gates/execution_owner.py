"""Execution owner records and liveness facts for accepted gate decisions."""

from __future__ import annotations

import os
import socket
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.ace.hooks.processes import is_process_running
from sase.core.process_identity import (
    current_boot_time_utc,
    identity_from_previous_boot,
    process_identity_matches,
    process_identity_token,
)
from sase.notification_gates.durability import file_lock
from sase.notification_gates.journal import (
    current_execution_failure,
    current_gate_execution_failure,
)
from sase.notification_gates.models import GateError
from sase.procs.identity import supervisor_is_alive
from sase.procs.store import get_proc


def current_execution_owner() -> dict[str, Any]:
    """Return the durable owner record for this process's gate execution."""
    proc_id = os.environ.get("SASE_PROC_ID", "").strip()
    if proc_id and get_proc(proc_id) is not None:
        return {"kind": "proc", "proc_id": proc_id}

    pid = os.getpid()
    owner: dict[str, Any] = {
        "kind": "process",
        "host": _current_host(),
        "pid": pid,
    }
    if proc_id:
        owner["proc_id"] = proc_id
    identity_token = process_identity_token(pid)
    if identity_token:
        owner["identity_token"] = identity_token
        started = _process_started_at_unix(identity_token)
        if started is not None:
            owner["started_at_unix"] = started
    return owner


def collect_gate_execution_facts(
    bundle_path: Path,
    receipt: Mapping[str, Any] | None,
    *,
    response_exists: bool,
) -> dict[str, Any]:
    """Collect raw host facts for the Rust gate-decision policy."""
    facts: dict[str, Any] = {
        "response_lock_held": _response_lock_is_held(bundle_path),
    }
    if response_exists:
        failure = current_gate_execution_failure(
            bundle_path, receipt, response_exists=True
        )
        if failure is not None:
            facts["post_response_failure"] = failure.to_wire()
    else:
        failure = current_execution_failure(bundle_path, receipt, response_exists=False)
        if failure is not None:
            facts["current_failure"] = failure.to_wire()

    if receipt is None:
        return facts
    owner = receipt.get("execution_owner")
    if isinstance(owner, str):
        _add_legacy_proc_facts(facts, owner)
    elif isinstance(owner, Mapping):
        kind = str(owner.get("kind") or "")
        if kind == "proc":
            proc_id = owner.get("proc_id")
            if isinstance(proc_id, str) and proc_id:
                _add_legacy_proc_facts(facts, proc_id)
        elif kind == "process":
            _add_process_owner_facts(facts, owner)
    return facts


def _response_lock_is_held(bundle_path: Path) -> bool:
    """Return whether another file description currently holds `.response.lock`."""
    try:
        with file_lock(bundle_path / ".response.lock", timeout=0.0):
            return False
    except GateError as exc:
        if exc.code == "lock_timeout":
            return True
        raise


def _add_legacy_proc_facts(facts: dict[str, Any], proc_id: str) -> None:
    proc = get_proc(proc_id)
    if proc is None:
        facts["legacy_proc_status"] = "missing"
        return
    facts["legacy_proc_status"] = proc.status
    if proc.status in {"pending", "running", "settling"} and proc.pid is not None:
        facts["legacy_proc_supervisor_alive"] = supervisor_is_alive(
            proc.pid, proc.supervisor_id
        )


def _add_process_owner_facts(facts: dict[str, Any], owner: Mapping[str, Any]) -> None:
    host = owner.get("host")
    if isinstance(host, str) and host:
        host_matches = host == _current_host()
        facts["owner_host_matches"] = host_matches
        if not host_matches:
            return
    else:
        return

    pid = _owner_pid(owner.get("pid"))
    if pid is None:
        return
    facts["owner_pid_running"] = is_process_running(pid)

    identity = owner.get("identity_token")
    if isinstance(identity, str) and identity:
        facts["owner_identity_matches"] = process_identity_matches(pid, identity)
        facts["owner_from_previous_boot"] = identity_from_previous_boot(identity)


def _owner_pid(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    return None


def _current_host() -> str:
    return socket.gethostname().strip() or "localhost"


def _process_started_at_unix(identity_token: str) -> float | None:
    boot_id, separator, ticks_text = identity_token.partition(":")
    if not separator:
        return None
    try:
        ticks = int(ticks_text)
    except ValueError:
        return None
    if boot_id.startswith("darwin-"):
        return float(ticks)
    boot_time = current_boot_time_utc()
    if boot_time is None:
        return None
    try:
        ticks_per_second = os.sysconf("SC_CLK_TCK")
    except (AttributeError, ValueError, OSError):
        return None
    if not isinstance(ticks_per_second, int) or ticks_per_second <= 0:
        return None
    return boot_time.timestamp() + (ticks / ticks_per_second)


__all__ = [
    "collect_gate_execution_facts",
    "current_execution_owner",
]
