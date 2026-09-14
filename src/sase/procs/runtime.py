"""Runtime markers and sidecars for one reserved proc-shell."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.config import (
    get_proc_runtime_orphan_horizon_seconds,
    get_proc_runtime_orphan_max_removals,
)
from sase.core.rust import require_rust_binding

from .paths import PROC_STORE_FILENAME, procs_dir

_PROC_GO_MARKER = ".proc_go"
_PROC_STARTED_MARKER = ".proc_started"
_REQUEST_SIDECAR_NAME = "request.json"
_SETTLEMENT_SIDECAR_NAME = "settlement.json"
_OPERATION_REQUEST_NAME = "operation-request.json"
_OPERATION_RESULT_NAME = "operation-result.json"

_LAUNCH_BARRIER_TIMEOUT_SECONDS = 30.0
_START_ACK_TIMEOUT_SECONDS = 20.0
_LAUNCH_BARRIER_TIMEOUT_ENV = "SASE_PROC_LAUNCH_BARRIER_TIMEOUT_SECONDS"
_START_ACK_TIMEOUT_ENV = "SASE_PROC_START_ACK_TIMEOUT_SECONDS"
PROC_RUNTIME_RETENTION_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _ProcRuntimeRetentionEntry:
    """One runtime-retention decision returned by the Rust owner."""

    proc_id: str
    path: str
    status: str
    reason: str
    size_bytes: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _ProcRuntimeRetentionEntry:
        return cls(
            proc_id=str(data.get("proc_id") or ""),
            path=str(data.get("path") or ""),
            status=str(data.get("status") or ""),
            reason=str(data.get("reason") or ""),
            size_bytes=int(data.get("size_bytes") or 0),
        )


@dataclass(frozen=True)
class _ProcRuntimeRetentionResult:
    """Structured outcome from one proc runtime retention owner pass."""

    runtime_root: Path
    apply: bool
    scanned: int
    selected: int
    removed: int
    skipped: int
    errors: int
    reclaimable_bytes: int
    reclaimed_bytes: int
    capped: bool
    entries: tuple[_ProcRuntimeRetentionEntry, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _ProcRuntimeRetentionResult:
        return cls(
            runtime_root=Path(str(data.get("runtime_root") or "")),
            apply=bool(data.get("apply", False)),
            scanned=int(data.get("scanned") or 0),
            selected=int(data.get("selected") or 0),
            removed=int(data.get("removed") or 0),
            skipped=int(data.get("skipped") or 0),
            errors=int(data.get("errors") or 0),
            reclaimable_bytes=int(data.get("reclaimable_bytes") or 0),
            reclaimed_bytes=int(data.get("reclaimed_bytes") or 0),
            capped=bool(data.get("capped", False)),
            entries=tuple(
                _ProcRuntimeRetentionEntry.from_dict(entry)
                for entry in data.get("entries") or ()
                if isinstance(entry, dict)
            ),
        )

    def describe(self) -> str:
        """Return a concise human summary for chops and disk-owner output."""
        if not self.selected:
            return f"nothing eligible under {self.runtime_root}"
        verb = "removed" if self.apply else "would remove"
        suffix = " (removal budget reached)" if self.capped else ""
        errors = f"; errors={self.errors}" if self.errors else ""
        return (
            f"{verb} {self.removed if self.apply else self.selected} proc runtime "
            f"dir(s) under {self.runtime_root}; scanned={self.scanned}, "
            f"reclaimable={self.reclaimable_bytes}, reclaimed={self.reclaimed_bytes}"
            f"{errors}{suffix}"
        )


def proc_runtime_dir(proc_id: str) -> Path:
    """Return ``~/.sase/procs/runtime/<proc_id>``."""
    return procs_dir() / "runtime" / proc_id


def delete_proc_runtime_dirs(
    proc_ids: Iterable[str],
    *,
    runtime_root: Path | None = None,
    store_path: Path | str | None = None,
) -> _ProcRuntimeRetentionResult:
    """Delete runtime sidecar directories for pruned proc rows."""
    root = runtime_root if runtime_root is not None else procs_dir() / "runtime"
    return _apply_runtime_retention(
        runtime_root=root,
        store_path=_store_path_for_runtime_root(root, store_path),
        pruned_proc_ids=tuple(str(proc_id) for proc_id in proc_ids),
        sweep_orphans=False,
        apply=True,
    )


def sweep_orphan_proc_runtime_dirs(
    retained_proc_ids: Iterable[str] = (),
    *,
    runtime_root: Path | None = None,
    store_path: Path | str | None = None,
    now: float | None = None,
    orphan_horizon_seconds: float | None = None,
    max_orphan_removals: int | None = None,
    apply: bool = True,
) -> _ProcRuntimeRetentionResult:
    """Delete proc runtime directories whose durable proc rows are gone."""
    del retained_proc_ids
    root = runtime_root if runtime_root is not None else procs_dir() / "runtime"
    return _apply_runtime_retention(
        runtime_root=root,
        store_path=_store_path_for_runtime_root(root, store_path),
        pruned_proc_ids=(),
        sweep_orphans=True,
        now=now,
        orphan_horizon_seconds=orphan_horizon_seconds,
        max_orphan_removals=max_orphan_removals,
        apply=apply,
    )


def _apply_runtime_retention(
    *,
    runtime_root: Path,
    store_path: Path,
    pruned_proc_ids: tuple[str, ...],
    sweep_orphans: bool,
    now: float | None = None,
    orphan_horizon_seconds: float | None = None,
    max_orphan_removals: int | None = None,
    apply: bool,
) -> _ProcRuntimeRetentionResult:
    _require_runtime_retention_wire_schema()
    binding = require_rust_binding("apply_proc_runtime_retention")
    request = {
        "schema_version": PROC_RUNTIME_RETENTION_WIRE_SCHEMA_VERSION,
        "store_path": str(store_path),
        "runtime_root": str(runtime_root),
        "now_epoch_seconds": time.time() if now is None else float(now),
        "orphan_horizon_seconds": float(
            get_proc_runtime_orphan_horizon_seconds()
            if orphan_horizon_seconds is None
            else orphan_horizon_seconds
        ),
        "max_orphan_removals": (
            get_proc_runtime_orphan_max_removals()
            if max_orphan_removals is None
            else int(max_orphan_removals)
        ),
        "apply": apply,
        "pruned_proc_ids": list(pruned_proc_ids),
        "sweep_orphans": sweep_orphans,
    }
    payload = binding(request)
    return _ProcRuntimeRetentionResult.from_dict(payload)


def _require_runtime_retention_wire_schema() -> None:
    binding = require_rust_binding("proc_runtime_retention_wire_schema_version")
    actual = int(binding())
    if actual != PROC_RUNTIME_RETENTION_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs proc runtime retention wire schema "
            f"{actual} is incompatible with Python schema "
            f"{PROC_RUNTIME_RETENTION_WIRE_SCHEMA_VERSION}"
        )


def _store_path_for_runtime_root(
    runtime_root: Path, store_path: Path | str | None
) -> Path:
    if store_path is not None:
        return Path(store_path)
    return runtime_root.parent / PROC_STORE_FILENAME


def proc_go_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _PROC_GO_MARKER


def proc_started_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _PROC_STARTED_MARKER


def proc_request_sidecar_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _REQUEST_SIDECAR_NAME


def proc_settlement_sidecar_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _SETTLEMENT_SIDECAR_NAME


def proc_operation_request_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _OPERATION_REQUEST_NAME


def proc_operation_result_path(proc_id: str) -> Path:
    return proc_runtime_dir(proc_id) / _OPERATION_RESULT_NAME


def launch_barrier_timeout_seconds() -> float:
    return _env_seconds(_LAUNCH_BARRIER_TIMEOUT_ENV, _LAUNCH_BARRIER_TIMEOUT_SECONDS)


def start_ack_timeout_seconds() -> float:
    return _env_seconds(_START_ACK_TIMEOUT_ENV, _START_ACK_TIMEOUT_SECONDS)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* so a reader never observes a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def read_json_object(path: Path) -> dict[str, Any]:
    """Return a JSON object from *path*, or ``{}`` when missing/invalid."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _env_seconds(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0.05, float(raw))
    except ValueError:
        return default


__all__ = [
    "launch_barrier_timeout_seconds",
    "delete_proc_runtime_dirs",
    "PROC_RUNTIME_RETENTION_WIRE_SCHEMA_VERSION",
    "proc_go_path",
    "proc_operation_request_path",
    "proc_operation_result_path",
    "proc_request_sidecar_path",
    "proc_runtime_dir",
    "proc_settlement_sidecar_path",
    "proc_started_path",
    "read_json_object",
    "start_ack_timeout_seconds",
    "sweep_orphan_proc_runtime_dirs",
    "write_json_atomic",
]
