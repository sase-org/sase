"""Projection maintenance actions for the local SASE daemon."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.integrations._daemon_lifecycle_config import (
    prepare_daemon_launch as default_prepare_daemon_launch,
)
from sase.integrations._daemon_lifecycle_inspection import inspect_daemon
from sase.integrations._daemon_lifecycle_types import (
    DaemonInspection,
    DaemonLaunch,
    DaemonLifecycleError,
)
from sase.integrations._daemon_lifecycle_values import positive_float


def run_daemon_rebuild(
    args: argparse.Namespace,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
    prepare_daemon_launch: Callable[
        [argparse.Namespace], DaemonLaunch
    ] = default_prepare_daemon_launch,
) -> dict[str, Any]:
    inspection = inspect_daemon(args)
    timeout = positive_float(getattr(args, "rebuild_timeout", None), 5.0)
    if inspection.state == "running" and inspection.rpc is not None:
        if inspection.rpc.get("available"):
            try:
                from sase.daemon.client import LocalDaemonClient

                client = LocalDaemonClient(
                    inspection.paths.socket_path,
                    timeout=timeout,
                )
                payload = client.rebuild(
                    storage_reset_only=bool(getattr(args, "storage_reset_only", False)),
                    surface=str(getattr(args, "surface", "all")),
                    project_id=getattr(args, "project_id", None),
                )
                _attach_source_export_health(payload, client)
            except Exception as exc:
                raise DaemonLifecycleError(
                    f"live daemon rebuild RPC failed: {exc}"
                ) from exc
            payload["source"] = "live_daemon_rpc"
            return payload
        raise DaemonLifecycleError(
            "daemon metadata is live but local RPC is unavailable; run "
            "`sase daemon doctor` before rebuilding"
        )
    if inspection.state not in {"stopped", "stale"}:
        raise DaemonLifecycleError(
            f"refusing one-shot rebuild from {inspection.state} daemon state: "
            f"{inspection.message}"
        )
    if not bool(getattr(args, "storage_reset_only", False)):
        raise DaemonLifecycleError(
            "source backfill rebuild requires a running daemon; use "
            "`sase daemon start` first, or pass --reset-storage for the "
            "one-shot projection replay recovery path"
        )

    launch = prepare_daemon_launch(
        argparse.Namespace(
            **{
                **vars(args),
                "foreground": False,
                "disable_mobile_http": True,
                "tokio_console": False,
            }
        )
    )
    argv = [*launch.argv, "--rebuild-once"]
    result = subprocess.run(  # noqa: S603
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise DaemonLifecycleError(
            f"one-shot rebuild failed with code {result.returncode}: {stderr}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DaemonLifecycleError(
            f"one-shot rebuild returned invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise DaemonLifecycleError("one-shot rebuild returned non-object JSON")
    payload["source"] = "one_shot_daemon_rebuild"
    return payload


def run_daemon_checkpoint(
    args: argparse.Namespace,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
) -> dict[str, Any]:
    inspection = _require_live_rpc(
        args,
        inspect_daemon=inspect_daemon,
        timeout_attr="checkpoint_timeout",
        operation="checkpoint",
    )
    try:
        from sase.daemon.client import LocalDaemonClient

        payload = LocalDaemonClient(
            inspection.paths.socket_path,
            timeout=positive_float(getattr(args, "checkpoint_timeout", None), 5.0),
        ).checkpoint(mode=str(getattr(args, "mode", "passive")))
    except Exception as exc:
        raise DaemonLifecycleError(f"live daemon checkpoint RPC failed: {exc}") from exc
    payload["source"] = "live_daemon_rpc"
    return payload


def run_daemon_backup(
    args: argparse.Namespace,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
) -> dict[str, Any]:
    inspection = _require_live_rpc(
        args,
        inspect_daemon=inspect_daemon,
        timeout_attr="backup_timeout",
        operation="backup",
    )
    try:
        from sase.daemon.client import LocalDaemonClient

        payload = LocalDaemonClient(
            inspection.paths.socket_path,
            timeout=positive_float(getattr(args, "backup_timeout", None), 5.0),
        ).backup(path=getattr(args, "backup_path", None))
    except Exception as exc:
        raise DaemonLifecycleError(f"live daemon backup RPC failed: {exc}") from exc
    payload["source"] = "live_daemon_rpc"
    return payload


def run_daemon_list_backups(
    args: argparse.Namespace,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
) -> dict[str, Any]:
    inspection = _require_live_rpc(
        args,
        inspect_daemon=inspect_daemon,
        timeout_attr="list_backups_timeout",
        operation="list backups",
    )
    try:
        from sase.daemon.client import LocalDaemonClient

        payload = LocalDaemonClient(
            inspection.paths.socket_path,
            timeout=positive_float(getattr(args, "list_backups_timeout", None), 5.0),
        ).list_backups(limit=int(getattr(args, "limit", 20) or 20))
    except Exception as exc:
        raise DaemonLifecycleError(
            f"live daemon list-backups RPC failed: {exc}"
        ) from exc
    payload["source"] = "live_daemon_rpc"
    return payload


def run_daemon_restore(
    args: argparse.Namespace,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
) -> dict[str, Any]:
    inspection = inspect_daemon(args)
    backup_path = Path(str(args.path))
    live_recovery = bool(getattr(args, "live_recovery", False))
    allow_host_mismatch = bool(getattr(args, "allow_host_mismatch", False))
    timeout = positive_float(getattr(args, "restore_timeout", None), 5.0)
    if (
        inspection.state == "running"
        and inspection.rpc
        and inspection.rpc.get("available")
    ):
        if not live_recovery:
            raise DaemonLifecycleError(
                "refusing live projection restore without --live-recovery"
            )
        try:
            from sase.daemon.client import LocalDaemonClient

            payload = LocalDaemonClient(
                inspection.paths.socket_path,
                timeout=timeout,
            ).restore(
                path=str(backup_path),
                live_recovery=True,
                allow_host_mismatch=allow_host_mismatch,
            )
        except Exception as exc:
            raise DaemonLifecycleError(
                f"live daemon restore RPC failed: {exc}"
            ) from exc
        payload["source"] = "live_daemon_rpc"
        return payload
    if inspection.state == "running":
        raise DaemonLifecycleError(
            "daemon metadata is live but local RPC is unavailable; run "
            "`sase daemon doctor` before restoring"
        )
    if inspection.state not in {"stopped", "stale"}:
        raise DaemonLifecycleError(
            f"refusing projection restore from {inspection.state} daemon state: "
            f"{inspection.message}"
        )
    return _restore_projection_backup_offline(
        backup_path=backup_path,
        target_path=inspection.paths.run_root / "projections" / "projection.sqlite",
        run_root=inspection.paths.run_root,
        allow_host_mismatch=allow_host_mismatch,
    )


def run_daemon_verify(
    args: argparse.Namespace,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
) -> dict[str, Any]:
    inspection = inspect_daemon(args)
    timeout = positive_float(getattr(args, "verify_timeout", None), 5.0)
    if inspection.state != "running" or not inspection.rpc:
        raise DaemonLifecycleError(
            f"daemon verify requires a running daemon: {inspection.message}"
        )
    if not inspection.rpc.get("available"):
        raise DaemonLifecycleError(
            "daemon metadata is live but local RPC is unavailable; run "
            "`sase daemon doctor` before verifying"
        )
    try:
        from sase.daemon.client import LocalDaemonClient

        return LocalDaemonClient(
            inspection.paths.socket_path,
            timeout=timeout,
        ).verify(
            surface=str(getattr(args, "surface", "all")),
            project_id=getattr(args, "project_id", None),
        )
    except Exception as exc:
        raise DaemonLifecycleError(f"live daemon verify RPC failed: {exc}") from exc


def run_daemon_diff(
    args: argparse.Namespace,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
) -> dict[str, Any]:
    inspection = inspect_daemon(args)
    timeout = positive_float(getattr(args, "diff_timeout", None), 5.0)
    if inspection.state != "running" or not inspection.rpc:
        raise DaemonLifecycleError(
            f"daemon diff requires a running daemon: {inspection.message}"
        )
    if not inspection.rpc.get("available"):
        raise DaemonLifecycleError(
            "daemon metadata is live but local RPC is unavailable; run "
            "`sase daemon doctor` before diffing"
        )
    try:
        from sase.daemon.client import LocalDaemonClient

        return LocalDaemonClient(
            inspection.paths.socket_path,
            timeout=timeout,
        ).diff(
            surface=str(getattr(args, "surface", "all")),
            project_id=getattr(args, "project_id", None),
            limit=int(getattr(args, "limit", 100) or 100),
            cursor=getattr(args, "cursor", None),
        )
    except Exception as exc:
        raise DaemonLifecycleError(f"live daemon diff RPC failed: {exc}") from exc


def _require_live_rpc(
    args: argparse.Namespace,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection],
    timeout_attr: str,
    operation: str,
) -> DaemonInspection:
    _ = positive_float(getattr(args, timeout_attr, None), 5.0)
    inspection = inspect_daemon(args)
    if inspection.state != "running" or not inspection.rpc:
        raise DaemonLifecycleError(
            f"daemon {operation} requires a running daemon: {inspection.message}"
        )
    if not inspection.rpc.get("available"):
        raise DaemonLifecycleError(
            "daemon metadata is live but local RPC is unavailable; run "
            f"`sase daemon doctor` before {operation}"
        )
    return inspection


def _restore_projection_backup_offline(
    *,
    backup_path: Path,
    target_path: Path,
    run_root: Path,
    allow_host_mismatch: bool,
) -> dict[str, Any]:
    backup_path = backup_path.expanduser()
    if not backup_path.is_file():
        raise DaemonLifecycleError(f"projection backup not found: {backup_path}")
    backups_dir = run_root / "backups"
    try:
        backup_path.resolve().relative_to(backups_dir.resolve())
    except ValueError as exc:
        raise DaemonLifecycleError(
            f"projection restore backup must be under {backups_dir}"
        ) from exc
    metadata_path = backup_path.with_name(backup_path.name + ".json")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DaemonLifecycleError(
            f"projection backup metadata is unreadable: {metadata_path}: {exc}"
        ) from exc
    if not allow_host_mismatch:
        metadata_host = str(metadata.get("host_identity") or "")
        from sase.daemon.paths import sanitize_host_identity

        current_host = sanitize_host_identity(os.environ.get("HOSTNAME"))
        if metadata_host and metadata_host != current_host:
            raise DaemonLifecycleError(
                "projection backup host "
                f"{metadata_host} does not match this host {current_host}; "
                "pass --allow-host-mismatch to restore it"
            )
    _validate_sqlite_projection_backup(backup_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    replaced_existing = target_path.exists()
    for sidecar in (
        target_path.with_name(target_path.name + "-wal"),
        target_path.with_name(target_path.name + "-shm"),
    ):
        if sidecar.exists():
            sidecar.unlink()
    shutil.copy2(backup_path, target_path)
    return {
        "schema_version": 1,
        "source": "offline_projection_restore",
        "report": {
            "schema_version": 1,
            "backup_path": str(backup_path),
            "restored_path": str(target_path),
            "bytes": target_path.stat().st_size,
            "replaced_existing": replaced_existing,
            "projection_only": True,
            "metadata": metadata,
        },
    }


def _validate_sqlite_projection_backup(path: Path) -> None:
    try:
        uri = f"file:{path}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'event_log'"
            ).fetchone()
    except sqlite3.Error as exc:
        raise DaemonLifecycleError(
            f"projection backup is not a readable SQLite database: {path}: {exc}"
        ) from exc
    if not row or int(row[0]) != 1:
        raise DaemonLifecycleError(
            f"projection backup is missing projection event_log table: {path}"
        )


def _attach_source_export_health(payload: dict[str, Any], client: Any) -> None:
    try:
        health = client.health()
    except Exception:
        return
    details = health.get("details") if isinstance(health, dict) else None
    projection = details.get("projection_db") if isinstance(details, dict) else None
    source_exports = (
        projection.get("source_exports") if isinstance(projection, dict) else None
    )
    if isinstance(source_exports, dict):
        existing = payload.get("source_exports")
        if (
            isinstance(existing, dict)
            and "retry" in existing
            and "retry" not in source_exports
        ):
            source_exports = {**source_exports, "retry": existing["retry"]}
        payload["source_exports"] = source_exports
