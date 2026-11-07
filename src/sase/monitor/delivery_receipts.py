"""Spawn-time launch receipts for ordinary continuation receivers.

Settlement spawns the follow-up receiver and then marks the delivery's
workspace. Name resolution cannot find the receiver until its runner boots
and its artifact is indexed under the reserved name, so a receiver that is
still booting (or queued for a runner slot) would otherwise look dead to the
terminal-delivery reconciliation that every ``list_monitors()`` caller runs.

The spawner already knows the receiver's real pid. This module records that
pid and its process identity beside the delivery record *before* the spawn
is marked, so receiver proofs can prove liveness from the spawn itself. A
receipt whose process is gone (or whose pid was recycled) proves nothing,
and the Rust verdict still fences that branch.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any, TypeGuard

from sase.finalizers.declaration_store import write_json_atomic

from .delivery import (
    DELIVERY_DIRNAME,
    delivery_record_filename,
    delivery_store_lock,
    update_delivery_workspace,
)
from .identity import process_identity, supervisor_is_alive

log = logging.getLogger(__name__)

RECEIVER_RECEIPT_DIRNAME = "receivers"
RECEIVER_RECEIPT_SCHEMA_VERSION = 1


def _receiver_launch_path(artifacts_dir: str | Path, key: Mapping[str, Any]) -> Path:
    """Return the receipt path for delivery *key* under *artifacts_dir*."""

    return (
        Path(artifacts_dir)
        / "continuation"
        / DELIVERY_DIRNAME
        / RECEIVER_RECEIPT_DIRNAME
        / delivery_record_filename(key)
    )


def _record_receiver_launch(
    artifacts_dir: str | Path,
    key: Mapping[str, Any],
    *,
    identity: str,
    pid: object,
    receiver_artifacts_dir: str | None,
) -> dict[str, Any] | None:
    """Persist the spawned receiver's launch receipt for delivery *key*.

    Records nothing and returns ``None`` when *pid* is not a positive int or
    *identity* is empty: such a receipt could never prove liveness.
    """

    if not _valid_pid(pid) or not identity:
        return None
    receipt: dict[str, Any] = {
        "schema_version": RECEIVER_RECEIPT_SCHEMA_VERSION,
        "key": {
            "monitor_id": str(key["monitor_id"]),
            "result_id": str(key["result_id"]),
            "branch": str(key["branch"]),
        },
        "identity": identity,
        "pid": pid,
        "process_identity": process_identity(pid),
        "receiver_artifacts_dir": receiver_artifacts_dir or None,
        "recorded_at": _now_iso(),
    }
    path = _receiver_launch_path(artifacts_dir, key)
    with delivery_store_lock(artifacts_dir):
        write_json_atomic(path, receipt)
    return receipt


def load_receiver_launch(
    artifacts_dir: str | Path,
    key: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the receipt for delivery *key*, or ``None`` if missing/unreadable.

    Never raises: proof collection must keep working on a damaged receipt.
    """

    try:
        path = _receiver_launch_path(artifacts_dir, key)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (KeyError, OSError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def receiver_launch_alive(
    receipt: Mapping[str, Any] | None,
    identity: str | None,
) -> bool:
    """Return whether *receipt* proves a live receiver process for *identity*.

    True only when the receipt names *identity* and its recorded pid is alive
    with the recorded process identity. A recycled pid fails the identity
    comparison and counts as dead.
    """

    if not receipt or not identity:
        return False
    if receipt.get("identity") != identity:
        return False
    pid = receipt.get("pid")
    if not _valid_pid(pid):
        return False
    recorded = receipt.get("process_identity")
    recorded_identity = recorded if isinstance(recorded, str) and recorded else None
    return supervisor_is_alive(pid, recorded_identity)


def mark_receiver_spawned(
    artifacts_dir: str | Path,
    key: Mapping[str, Any],
    *,
    identity: str,
    pid: object,
    receiver_artifacts_dir: str | None,
    workspace_identity: str | None,
) -> None:
    """Record the spawned receiver's launch receipt, then its workspace.

    The receipt lands first so that from the instant any receiver proof can
    show ``spawn_recorded`` (the delivery's ``workspace_identity``), the
    receipt that proves the receiver's process is already on disk. A receipt
    write failure is best effort: it must not turn a successful spawn into a
    failed launch.
    """

    try:
        _record_receiver_launch(
            artifacts_dir,
            key,
            identity=identity,
            pid=pid,
            receiver_artifacts_dir=receiver_artifacts_dir,
        )
    except Exception:  # noqa: BLE001 - the receipt is best-effort evidence
        log.warning(
            "failed to record receiver launch receipt for %s", identity, exc_info=True
        )
    update_delivery_workspace(
        artifacts_dir,
        key,
        workspace_identity=workspace_identity,
    )


def _valid_pid(pid: object) -> TypeGuard[int]:
    return isinstance(pid, int) and not isinstance(pid, bool) and pid > 0


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "RECEIVER_RECEIPT_DIRNAME",
    "RECEIVER_RECEIPT_SCHEMA_VERSION",
    "load_receiver_launch",
    "mark_receiver_spawned",
    "receiver_launch_alive",
]
