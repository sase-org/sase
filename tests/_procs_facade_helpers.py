"""Shared proc/reserve/runtime-dir builders for the procs-facade test files."""

from __future__ import annotations

import os
from pathlib import Path

from sase.procs import Proc, ProcReserve
from sase.procs.service_meta import ProcServiceBlock


def _proc(
    proc_id: str,
    *,
    kind: str = "command",
    status: str = "pending",
    created_at: str = "2026-07-25T12:00:00Z",
    label: str = "Build docs",
    project: str | None = "sase",
    session_id: str | None = "session-a",
    tags: list[str] | None = None,
    command: list[str] | None = None,
    cl_name: str | None = "docs_refresh",
    shell_name: str | None = None,
    service: ProcServiceBlock | None = None,
) -> Proc:
    return Proc(
        proc_id=proc_id,
        label=label,
        kind=kind,
        status=status,
        command=command or ["just", "docs"],
        cwd="/tmp",
        project=project,
        session_id=session_id,
        origin="test",
        cl_name=cl_name,
        tags=tags or ["docs"],
        created_at=created_at,
        log_path=f"/tmp/{proc_id}.log",
        shell_name=shell_name,
        service=service,
    )


def _reserve(
    proc_id: str,
    *,
    shell_name: str = "agent--build",
    fingerprint: str = "fingerprint",
    concurrency_keys: list[str] | None = None,
    service: ProcServiceBlock | None = None,
) -> ProcReserve:
    return ProcReserve(
        proc_id=proc_id,
        label="Build docs",
        argv=["just", "docs"],
        cwd="/tmp",
        project="sase",
        workspace_num=10,
        session_id="session-a",
        origin="test",
        tags=["docs"],
        created_at="2026-07-25T12:00:00Z",
        log_path=f"/tmp/{proc_id}.log",
        shell_name=shell_name,
        concurrency_keys=concurrency_keys or ["docs"],
        request_fingerprint=fingerprint,
        reserved_by="agent-one",
        timeout_seconds=30,
        service=service,
    )


def _proc_runtime_dir_for_store(store: Path, proc_id: str) -> Path:
    return store.parent / "runtime" / proc_id


def _aged_runtime_dir(store: Path, proc_id: str, *, now: float, age: float) -> Path:
    runtime_dir = _proc_runtime_dir_for_store(store, proc_id)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    payload = runtime_dir / "request.json"
    payload.write_text("{}", encoding="utf-8")
    timestamp = now - age
    os.utime(payload, (timestamp, timestamp))
    os.utime(runtime_dir, (timestamp, timestamp))
    return runtime_dir
