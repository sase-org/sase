"""Start, stop, and rebuild actions for the local SASE daemon."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.integrations._daemon_lifecycle_config import (
    prepare_daemon_launch as default_prepare_daemon_launch,
)
from sase.integrations._daemon_lifecycle_inspection import inspect_daemon
from sase.integrations._daemon_lifecycle_process import (
    executable_matches_metadata,
    process_is_live,
    terminate_process as default_terminate_process,
)
from sase.integrations._daemon_lifecycle_types import (
    DEFAULT_STOP_TIMEOUT_SECONDS,
    KillFn,
    PopenFactory,
    SleepFn,
    DaemonInspection,
    DaemonLaunch,
    DaemonLifecycleError,
)
from sase.integrations._daemon_lifecycle_values import int_value, positive_float


def run_daemon_start(
    args: argparse.Namespace,
    *,
    popen: PopenFactory = subprocess.Popen,
    sleep: SleepFn = time.sleep,
    prepare_daemon_launch: Callable[
        [argparse.Namespace], DaemonLaunch
    ] = default_prepare_daemon_launch,
    background_start_waiter: Callable[
        [DaemonLaunch, subprocess.Popen[Any], SleepFn], DaemonInspection
    ]
    | None = None,
    terminate_process: Callable[
        [subprocess.Popen[Any]], None
    ] = default_terminate_process,
) -> int:
    wait = background_start_waiter or wait_for_background_start
    launch = prepare_daemon_launch(args)
    if launch.foreground:
        print("Starting SASE daemon in the foreground.")
        proc = popen(launch.argv)
        try:
            return int(proc.wait())
        except KeyboardInterrupt:
            terminate_process(proc)
            return 130

    launch.paths.run_root.mkdir(parents=True, exist_ok=True)
    log_path = launch.paths.run_root / "daemon.log"
    print(f"Starting SASE daemon in the background. Log: {log_path}")
    with open(log_path, "ab") as log_file:
        proc = popen(
            launch.argv,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    inspection = wait(launch, proc, sleep)
    if inspection.state == "running":
        if inspection.rpc and inspection.rpc.get("available"):
            print("SASE daemon started; local RPC health is available.")
        else:
            print(
                "SASE daemon started; ownership metadata is available. "
                "Local RPC health is unavailable until the daemon transport is ready."
            )
        return 0
    raise DaemonLifecycleError(inspection.message)


def run_daemon_stop(
    args: argparse.Namespace,
    *,
    kill: KillFn = os.kill,
    sleep: SleepFn = time.sleep,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
    process_is_live: Callable[[int], bool] = process_is_live,
    executable_matches_metadata: Callable[
        [int, dict[str, Any]], bool
    ] = executable_matches_metadata,
) -> int:
    inspection = inspect_daemon(args)
    if inspection.state == "stopped":
        print("SASE daemon is not running.")
        return 0
    if inspection.state != "running" or inspection.metadata is None:
        raise DaemonLifecycleError(
            f"refusing to stop daemon from {inspection.state} metadata: "
            f"{inspection.message}"
        )

    pid = int_value(inspection.metadata.get("pid"))
    if pid is None:
        raise DaemonLifecycleError("refusing to stop daemon with missing pid")
    if not executable_matches_metadata(pid, inspection.metadata):
        raise DaemonLifecycleError(
            f"refusing to signal pid {pid}; executable does not match metadata"
        )

    kill(pid, signal.SIGTERM)
    timeout = positive_float(
        getattr(args, "stop_timeout", None),
        DEFAULT_STOP_TIMEOUT_SECONDS,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_is_live(pid):
            print(f"Stopped SASE daemon pid {pid}.")
            return 0
        sleep(0.1)
    raise DaemonLifecycleError(
        f"sent SIGTERM to daemon pid {pid}, but it is still running"
    )


def repair_stale_lock(
    args: argparse.Namespace,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
) -> dict[str, Any]:
    inspection = inspect_daemon(args)
    if inspection.state != "stale":
        raise DaemonLifecycleError(
            f"refusing stale-lock repair from {inspection.state} daemon state: "
            f"{inspection.message}"
        )
    try:
        from sase.integrations._daemon_lifecycle_inspection import lock_file_is_held

        lock_held = lock_file_is_held(inspection.lock_path)
    except Exception as exc:
        raise DaemonLifecycleError(
            f"could not verify daemon lock ownership: {exc}"
        ) from exc
    if lock_held is not False:
        raise DaemonLifecycleError(
            f"refusing stale-lock repair because {inspection.lock_path} "
            "may still be held"
        )

    removed: list[str] = []
    skipped: list[str] = []
    for path in (
        inspection.paths.metadata_path,
        inspection.lock_path,
        inspection.paths.socket_path,
    ):
        if path == inspection.paths.socket_path and not _is_under(
            path, inspection.paths.run_root
        ):
            skipped.append(str(path))
            continue
        if not _is_under(path, inspection.paths.run_root):
            skipped.append(str(path))
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise DaemonLifecycleError(
                f"failed to remove stale daemon runtime file {path}: {exc}"
            ) from exc
        removed.append(str(path))
    return {
        "state": "repaired",
        "action": "remove_stale_lock",
        "risk": "runtime_only",
        "removed": removed,
        "skipped": skipped,
        "message": "removed stale daemon runtime lock state",
    }


def _is_under(path: os.PathLike[str] | str, parent: os.PathLike[str] | str) -> bool:
    try:
        return (
            Path(path)
            .resolve(strict=False)
            .is_relative_to(Path(parent).resolve(strict=False))
        )
    except OSError:
        return False


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


def wait_for_background_start(
    launch: DaemonLaunch,
    proc: subprocess.Popen[Any],
    sleep: SleepFn,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
) -> DaemonInspection:
    deadline = time.monotonic() + launch.startup_timeout_seconds
    last = DaemonInspection(
        state="stopped",
        paths=launch.paths,
        message="daemon did not publish ownership metadata yet",
    )
    args = argparse.Namespace(
        sase_home=str(launch.paths.sase_home),
        run_root=str(launch.paths.run_root),
        socket_path=str(launch.paths.socket_path),
    )
    while time.monotonic() < deadline:
        exit_code = proc.poll()
        if exit_code is not None:
            return DaemonInspection(
                state="stopped",
                paths=launch.paths,
                message=f"daemon exited before startup completed with code {exit_code}",
            )
        last = inspect_daemon(args)
        if last.state == "running":
            return last
        sleep(0.1)
    return last
