"""Shared settlement-test helpers.

Public helpers for the ``test_settlement*`` modules. Names are public so the
split modules can import them; the module itself is private (``_``-prefixed)
so no ``_``-prefixed name is ever imported across modules.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_claim, tool_run_show
from sase.notifications.store import load_notifications
from sase.procs.models import Proc
from sase.procs.runtime import (
    proc_request_sidecar_path,
    write_json_atomic,
)
from sase.procs.settlement import settle_named_proc
from sase.procs.store import append_proc
from sase.tool.argv import resolve_run_argv
from sase.tool.handoff import reserve_handoff_run
from sase.tool.liveness import current_boot_id

_DEAD_SUPERVISOR = "ffffeeee-dead-beef-0000-111122223333:1"


def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_PROC_LOG_PATH",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
        "SASE_BEAD_ID",
        "SASE_BEAD",
        "SASE_WORKSPACE_NUM",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def dead_identity() -> tuple[int, str, str]:
    """Return ``(pid, boot_id, identity)`` of a process that already exited."""

    finished = subprocess.Popen(["true"])
    finished.wait()
    boot = current_boot_id()
    return finished.pid, boot, f"{boot}:1"


def reserve(
    owner_kind: str, owner_id: str, words: tuple[str, ...] = ("--", "true")
) -> str:
    reservation = reserve_handoff_run(
        resolve_run_argv(list(words)), owner_kind=owner_kind, owner_id=owner_id
    )
    assert reservation.reserved, reservation.error
    return reservation.run_id


def reserve_with_dead_launcher(owner_id: str) -> str:
    """Reserve a ``created`` proc-owned run from a launcher that then exits."""

    code = (
        "import os\n"
        "from sase.tool.argv import resolve_run_argv\n"
        "from sase.tool.handoff import reserve_handoff_run\n"
        "r = reserve_handoff_run(resolve_run_argv(['--', 'true']), "
        f"owner_kind='proc', owner_id={owner_id!r})\n"
        "print(r.run_id, flush=True)\n"
        "os._exit(0)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=dict(os.environ),
    )
    run_id = completed.stdout.strip()
    assert get_run(run_id)["state"] == "created"
    return run_id


def claim(
    run_id: str,
    owner_kind: str,
    owner_id: str,
    *,
    identity: tuple[int, str, str] | None = None,
    owner_log_path: str | None = None,
) -> None:
    pid, boot, token = identity or dead_identity()
    request: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "owner_kind": owner_kind,
        "owner_id": owner_id,
        "wrapper_pid": pid,
        "boot_id": boot,
        "process_start_identity": token,
    }
    if owner_log_path is not None:
        request["owner_log_path"] = owner_log_path
    assert tool_run_claim(request)["outcome"] == "claimed"


def get_run(run_id: str) -> dict[str, Any]:
    run = tool_run_show(run_id)["run"]
    assert isinstance(run, dict)
    return run


def terminal_fact(
    kind: str,
    owner_id: str,
    reason: str,
    *,
    exit_code: int | None = None,
    stop: bool = False,
) -> dict[str, Any]:
    fact: dict[str, Any] = {
        "kind": kind,
        "id": owner_id,
        "state": "terminal",
        "termination_reason": reason,
        "stop_requested": stop,
    }
    if exit_code is not None:
        fact["exit_code"] = exit_code
    return fact


def tool_run_notifications() -> list[Any]:
    return [
        item
        for item in load_notifications(include_dismissed=True)
        if item.sender == "tool-run"
    ]


def expected_notification_id(run_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"sase:tool-run-settled:{run_id}"))


def fabricate_proc(tmp_path: Path, proc_id: str, run_id: str | None) -> Proc:
    """Append a running named-proc row whose supervisor is gone."""

    proc = Proc(
        proc_id=proc_id,
        label="tool:test",
        kind="command",
        status="running",
        lifecycle="named-proc",
        command=["true"],
        argv=["true"],
        cwd=str(tmp_path),
        origin="tool-run",
        created_at="2026-07-25T12:00:00Z",
        log_path=str(tmp_path / f"{proc_id}.log"),
        request_fingerprint=f"tool-run:{run_id or proc_id}",
        reserved_by="test",
        supervisor_id=_DEAD_SUPERVISOR,
        pid=os.getpid(),
    )
    append_proc(proc)
    if run_id is not None:
        write_json_atomic(
            proc_request_sidecar_path(proc_id),
            {"followup": {"kind": "tool-run", "run_id": run_id}},
        )
    return proc


def settle_fabricated(
    proc_id: str,
    *,
    status: str,
    reason: str,
    exit_code: int | None,
    message: str = "settled",
) -> Proc:
    return settle_named_proc(
        proc_id,
        supervisor_id=_DEAD_SUPERVISOR,
        status=status,
        message=message,
        termination_reason=reason,
        exit_code=exit_code,
    )
