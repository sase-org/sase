"""Python lifecycle glue for the local SASE daemon."""

from __future__ import annotations

import argparse
import hashlib
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

from sase.integrations import _daemon_lifecycle_actions as _actions
from sase.integrations import _daemon_lifecycle_inspection as _inspection
from sase.integrations import _daemon_lifecycle_process as _process
from sase.integrations import _daemon_lifecycle_types as _types
from sase.integrations import _daemon_lifecycle_values as _values
from sase.integrations._daemon_lifecycle_actions import (
    repair_stale_lock,
    run_daemon_backup,
    run_daemon_checkpoint,
    run_daemon_diff,
    run_daemon_list_backups,
    run_daemon_rebuild,
    run_daemon_restore,
    run_daemon_start,
    run_daemon_stop,
    run_daemon_verify,
    wait_for_background_start,
)
from sase.integrations._daemon_lifecycle_config import (
    host_identity_from_env,
    load_daemon_config,
    prepare_daemon_launch,
    resolve_gateway_command,
    runtime_paths_from_args,
)
from sase.integrations._daemon_lifecycle_diagnostics import (
    doctor_payload,
    inspection_to_dict,
    print_status,
)
from sase.integrations._daemon_lifecycle_inspection import (
    read_metadata,
    try_health_rpc,
)

DEFAULT_STARTUP_TIMEOUT_SECONDS = _types.DEFAULT_STARTUP_TIMEOUT_SECONDS
DEFAULT_STOP_TIMEOUT_SECONDS = _types.DEFAULT_STOP_TIMEOUT_SECONDS
LOCK_FILENAME = _types.LOCK_FILENAME
LOCK_METADATA_FILENAME = _types.LOCK_METADATA_FILENAME
LOCK_SCHEMA_VERSION = _types.LOCK_SCHEMA_VERSION
SOCKET_FILENAME = _types.SOCKET_FILENAME
KillFn = _types.KillFn
PopenFactory = _types.PopenFactory
SleepFn = _types.SleepFn
_DaemonInspection = _types.DaemonInspection
_DaemonLaunch = _types.DaemonLaunch
_DaemonLifecycleConfig = _types.DaemonLifecycleConfig
_DaemonLifecycleError = _types.DaemonLifecycleError
_DaemonRuntimePaths = _types.DaemonRuntimePaths
_command_value = _values.command_value
_int_value = _values.int_value
_optional_path = _values.optional_path
_positive_float = _values.positive_float

__all__ = [
    "DEFAULT_STARTUP_TIMEOUT_SECONDS",
    "DEFAULT_STOP_TIMEOUT_SECONDS",
    "LOCK_FILENAME",
    "LOCK_METADATA_FILENAME",
    "LOCK_SCHEMA_VERSION",
    "SOCKET_FILENAME",
    "KillFn",
    "PopenFactory",
    "SleepFn",
    "_DaemonInspection",
    "_DaemonLaunch",
    "_DaemonLifecycleConfig",
    "_DaemonLifecycleError",
    "_DaemonRuntimePaths",
    "_command_value",
    "_doctor_payload",
    "_executable_matches_metadata",
    "_host_identity_from_env",
    "_inspect_daemon",
    "_inspection_to_dict",
    "_int_value",
    "_load_daemon_config",
    "_optional_path",
    "_positive_float",
    "_prepare_daemon_launch",
    "_print_status",
    "_process_is_live",
    "_read_metadata",
    "_resolve_gateway_command",
    "_repair_stale_lock",
    "_run_daemon_diff",
    "_run_daemon_backup",
    "_run_daemon_checkpoint",
    "_run_daemon_list_backups",
    "_run_daemon_rebuild",
    "_run_daemon_restore",
    "_run_daemon_start",
    "_run_daemon_stop",
    "_run_daemon_verify",
    "_runtime_paths_from_args",
    "_terminate_process",
    "_try_health_rpc",
    "_wait_for_background_start",
    "handle_daemon_backup",
    "handle_daemon_checkpoint",
    "handle_daemon_diff",
    "handle_daemon_doctor",
    "handle_daemon_list_backups",
    "handle_daemon_rebuild",
    "handle_daemon_restore",
    "handle_daemon_scheduler",
    "handle_daemon_start",
    "handle_daemon_status",
    "handle_daemon_stop",
    "handle_daemon_verify",
    "signal",
]


def handle_daemon_start(args: argparse.Namespace) -> int:
    """CLI wrapper for ``sase daemon start``."""
    try:
        return _run_daemon_start(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def handle_daemon_status(args: argparse.Namespace) -> int:
    """CLI wrapper for ``sase daemon status``."""
    inspection = _inspect_daemon(args)
    if getattr(args, "json_output", False):
        print(json.dumps(_inspection_to_dict(inspection), indent=2, sort_keys=True))
    else:
        _print_status(inspection)
    return 0


def handle_daemon_scheduler(args: argparse.Namespace) -> int:
    """CLI wrapper for daemon scheduler inspection and recovery commands."""
    sub = getattr(args, "daemon_scheduler_subcommand", None)
    if sub == "status":
        return _handle_daemon_scheduler_status(args)
    if sub == "cancel":
        return _handle_daemon_scheduler_cancel(args)
    print("Usage: sase daemon scheduler {status,cancel}", file=sys.stderr)
    return 1


def handle_daemon_stop(args: argparse.Namespace) -> int:
    """CLI wrapper for ``sase daemon stop``."""
    try:
        return _run_daemon_stop(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def handle_daemon_doctor(args: argparse.Namespace) -> int:
    """Run daemon lifecycle and projection diagnostics."""
    if getattr(args, "repair_stale_lock", False):
        try:
            repair_payload = _repair_stale_lock(args)
        except _DaemonLifecycleError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if getattr(args, "json_output", False):
            print(json.dumps(repair_payload, indent=2, sort_keys=True))
        else:
            print(f"Repair: {repair_payload['action']} {repair_payload['state']}")
            removed = repair_payload.get("removed", [])
            if isinstance(removed, list):
                for path in removed:
                    print(f"- removed {path}")
            skipped = repair_payload.get("skipped", [])
            if isinstance(skipped, list):
                for path in skipped:
                    print(f"- skipped {path}")
        return 0
    inspection = _inspect_daemon(args)
    payload = _doctor_payload(inspection)
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_status(inspection)
        print(f"Doctor: {payload['doctor']['state']}")
        for check in payload["doctor"]["checks"]:
            print(f"- {check['name']}: {check['state']} - {check['message']}")
        repair_actions = payload.get("repair_actions", [])
        if repair_actions:
            print("Repair actions:")
            for action in repair_actions:
                if not isinstance(action, dict):
                    continue
                command = action.get("command")
                suffix = f" -> {command}" if command else ""
                print(
                    "- {id}: {risk} - {explanation}{suffix}".format(
                        id=action.get("id", "unknown"),
                        risk=action.get("risk", "unknown"),
                        explanation=action.get("explanation", ""),
                        suffix=suffix,
                    )
                )
    return 0


def handle_daemon_rebuild(args: argparse.Namespace) -> int:
    """Rebuild daemon projections through a live daemon or one-shot Rust path."""
    try:
        payload = _run_daemon_rebuild(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        mode = payload.get("mode", "projection_storage_rebuild")
        limitation = payload.get("limitation")
        source = payload.get("source")
        print(f"Rebuild: {mode} completed via {source}.")
        if limitation:
            prefix = (
                "WARNING: reset-storage limitation"
                if payload.get("storage_reset_only")
                else "Limitation"
            )
            print(f"{prefix}: {limitation}")
        if payload.get("elapsed_ms") is not None:
            print(f"Elapsed: {payload['elapsed_ms']} ms")
        source_exports = payload.get("source_exports")
        if isinstance(source_exports, dict):
            print(
                "Source exports: {state} pending={pending} failed={failed} "
                "conflicts={conflict}".format(
                    state=source_exports.get("state", "unknown"),
                    pending=source_exports.get("pending", 0),
                    failed=source_exports.get("failed", 0),
                    conflict=source_exports.get("conflict", 0),
                )
            )
            retry = source_exports.get("retry")
            if isinstance(retry, dict):
                print(
                    "Source export retry: attempted={attempted} applied={applied} "
                    "failed={failed} conflicts={conflict} preserved_conflicts={preserved}".format(
                        attempted=retry.get("attempted", 0),
                        applied=retry.get("applied", 0),
                        failed=retry.get("failed", 0),
                        conflict=retry.get("conflict", 0),
                        preserved=retry.get("preserved_conflicts", 0),
                    )
                )
        for summary in payload.get("summaries", []):
            if isinstance(summary, dict):
                _print_indexing_summary(summary)
        if payload.get("next_command"):
            print(f"Next: {payload['next_command']}")
    return 0


def handle_daemon_checkpoint(args: argparse.Namespace) -> int:
    """Checkpoint the projection WAL through a live daemon."""
    try:
        payload = _run_daemon_checkpoint(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        report = payload.get("report", {})
        print(
            "Checkpoint: mode={mode} busy={busy} frames={done}/{log}".format(
                mode=report.get("mode", getattr(args, "mode", "passive")),
                busy=report.get("busy", 0),
                done=report.get("checkpointed_frames", 0),
                log=report.get("log_frames", 0),
            )
        )
    return 0


def handle_daemon_backup(args: argparse.Namespace) -> int:
    """Create a projection backup through a live daemon."""
    try:
        payload = _run_daemon_backup(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        report = payload.get("report", {})
        print(
            "Backup: {path} ({bytes} bytes)".format(
                path=report.get("path", "unknown"),
                bytes=report.get("bytes", 0),
            )
        )
    return 0


def handle_daemon_list_backups(args: argparse.Namespace) -> int:
    """List projection backups through a live daemon."""
    try:
        payload = _run_daemon_list_backups(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        backups = payload.get("backups", {}).get("backups", [])
        print(f"Backups: {len(backups)}")
        for backup in backups:
            if isinstance(backup, dict):
                metadata = backup.get("metadata", {})
                print(
                    "- {path} seq={seq} created={created}".format(
                        path=backup.get("path", "unknown"),
                        seq=metadata.get("event_max_sequence", 0)
                        if isinstance(metadata, dict)
                        else 0,
                        created=metadata.get("created_at", "")
                        if isinstance(metadata, dict)
                        else "",
                    )
                )
    return 0


def handle_daemon_restore(args: argparse.Namespace) -> int:
    """Restore a projection backup without touching source stores."""
    try:
        payload = _run_daemon_restore(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        report = payload.get("report", {})
        print(
            "Restore: {backup} -> {target} projection_only={projection_only}".format(
                backup=report.get("backup_path", getattr(args, "path", "")),
                target=report.get("restored_path", "unknown"),
                projection_only=report.get("projection_only", True),
            )
        )
    return 0


def handle_daemon_verify(args: argparse.Namespace) -> int:
    """Verify daemon shadow projections through a live daemon."""
    try:
        payload = _run_daemon_verify(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        state = "ok" if payload.get("ok") else "degraded"
        print(f"Verify: {state}")
        for summary in payload.get("summaries", []):
            if isinstance(summary, dict):
                _print_indexing_summary(summary)
    return 0 if payload.get("ok") else 1


def handle_daemon_diff(args: argparse.Namespace) -> int:
    """Print bounded daemon shadow projection diffs."""
    try:
        payload = _run_daemon_diff(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Diff: {payload.get('surface', 'all')}")
        for record in payload.get("records", []):
            if isinstance(record, dict):
                print(
                    "- {category} {domain} {handle}: {message}".format(
                        category=record.get("category", "unknown"),
                        domain=record.get("domain", "unknown"),
                        handle=record.get("handle") or record.get("source_path") or "",
                        message=record.get("message", ""),
                    )
                )
        if payload.get("next_cursor"):
            print(f"Next cursor: {payload['next_cursor']}")
        if payload.get("next_command"):
            print(f"Next: {payload['next_command']}")
    counts = payload.get("counts")
    has_diff = (
        isinstance(counts, dict)
        and sum(
            int(counts.get(key, 0)) for key in ("missing", "stale", "extra", "corrupt")
        )
        > 0
    )
    return 1 if has_diff else 0


def _print_indexing_summary(summary: dict[str, Any]) -> None:
    counts = summary.get("diff_counts", {})
    if not isinstance(counts, dict):
        counts = {}
    print(
        "- {surface}: {state} scanned={scanned} indexed={indexed} skipped={skipped} "
        "parse_failures={parse_failures} missing={missing} stale={stale} "
        "extra={extra} corrupt={corrupt} elapsed_ms={elapsed}".format(
            surface=summary.get("surface", "unknown"),
            state=summary.get("state", "unknown"),
            scanned=summary.get("scanned_sources", 0),
            indexed=summary.get("indexed_rows", 0),
            skipped=summary.get("skipped_rows", 0),
            parse_failures=summary.get("parse_failures", 0),
            missing=counts.get("missing", 0),
            stale=counts.get("stale", 0),
            extra=counts.get("extra", 0),
            corrupt=counts.get("corrupt", 0),
            elapsed=summary.get("elapsed_ms", 0),
        )
    )
    if summary.get("next_command"):
        print(f"  Next: {summary['next_command']}")


def _handle_daemon_scheduler_status(args: argparse.Namespace) -> int:
    from sase.daemon.client import LocalDaemonClient, LocalDaemonError

    inspection = _inspect_daemon(args)
    if (
        inspection.state != "running"
        or not inspection.rpc
        or not inspection.rpc.get("available")
    ):
        print(
            f"Error: daemon scheduler status requires a running daemon: {inspection.message}",
            file=sys.stderr,
        )
        return 1
    try:
        payload = LocalDaemonClient(
            inspection.paths.socket_path, timeout=5.0
        ).scheduler_status(
            project_id=str(args.project_id),
            batch_id=str(args.batch_id),
        )
    except LocalDaemonError as exc:
        print(f"Error: daemon scheduler status failed: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_scheduler_status(payload)
    return 0


def _handle_daemon_scheduler_cancel(args: argparse.Namespace) -> int:
    from sase.daemon.client import LocalDaemonClient, LocalDaemonError
    from sase.daemon.scheduler import SchedulerCancel, cancel_scheduler_batch

    inspection = _inspect_daemon(args)
    if (
        inspection.state != "running"
        or not inspection.rpc
        or not inspection.rpc.get("available")
    ):
        print(
            f"Error: daemon scheduler cancel requires a running daemon: {inspection.message}",
            file=sys.stderr,
        )
        return 1
    request = SchedulerCancel(
        project_id=str(args.project_id),
        batch_id=str(args.batch_id),
        slot_id=getattr(args, "slot_id", None),
        reason=getattr(args, "reason", None) or "operator_recovery",
        idempotency_key=getattr(args, "idempotency_key", None)
        or _scheduler_cancel_idempotency_key(args),
    )
    try:
        payload = cancel_scheduler_batch(
            LocalDaemonClient(inspection.paths.socket_path, timeout=5.0),
            request,
        )
    except LocalDaemonError as exc:
        print(f"Error: daemon scheduler cancel failed: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_scheduler_status(payload, prefix="Cancel")
    return 0


def _scheduler_cancel_idempotency_key(args: argparse.Namespace) -> str:
    raw = "|".join(
        str(value or "")
        for value in (
            getattr(args, "project_id", None),
            getattr(args, "batch_id", None),
            getattr(args, "slot_id", None),
            getattr(args, "reason", None),
        )
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"scheduler-recovery:{digest}"


def _print_scheduler_status(
    payload: dict[str, Any], *, prefix: str = "Scheduler"
) -> None:
    raw_handle = payload.get("handle")
    handle: dict[str, Any] = raw_handle if isinstance(raw_handle, dict) else {}
    print(
        "{prefix}: batch={batch} project={project} queue={queue} status={status} slots={slots}".format(
            prefix=prefix,
            batch=handle.get("batch_id", "unknown"),
            project=handle.get("project_id", "unknown"),
            queue=handle.get("queue_id", "unknown"),
            status=handle.get("status", "unknown"),
            slots=handle.get("slot_count", 0),
        )
    )
    for slot in payload.get("slots", []):
        if not isinstance(slot, dict):
            continue
        raw_task = slot.get("task_id")
        task: dict[str, Any] = raw_task if isinstance(raw_task, dict) else {}
        print(
            "- {slot_id}: {status} position={position} terminal={terminal} reason={reason}".format(
                slot_id=task.get("slot_id") or slot.get("slot_id") or "unknown",
                status=slot.get("status", "unknown"),
                position=slot.get("queued_position"),
                terminal=slot.get("terminal", False),
                reason=slot.get("reason"),
            )
        )


def _load_daemon_config() -> _DaemonLifecycleConfig:
    return load_daemon_config()


def _prepare_daemon_launch(
    args: argparse.Namespace,
    *,
    config: _DaemonLifecycleConfig | None = None,
) -> _DaemonLaunch:
    if config is None:
        config = _load_daemon_config()
    return prepare_daemon_launch(
        args,
        config=config,
        gateway_command_resolver=_resolve_gateway_command,
    )


def _runtime_paths_from_args(
    args: argparse.Namespace,
    *,
    config: _DaemonLifecycleConfig | None = None,
) -> _DaemonRuntimePaths:
    if config is None:
        config = _load_daemon_config()
    return runtime_paths_from_args(args, config=config)


def _host_identity_from_env() -> str:
    return host_identity_from_env()


def _resolve_gateway_command() -> tuple[str, ...]:
    return resolve_gateway_command()


def _inspect_daemon(args: argparse.Namespace) -> _DaemonInspection:
    return _inspection.inspect_daemon(
        args,
        runtime_paths_from_args=_runtime_paths_from_args,
        host_identity_from_env=_host_identity_from_env,
        process_is_live=_process_is_live,
        executable_matches_metadata=_executable_matches_metadata,
        metadata_reader=_read_metadata,
        health_rpc=_try_health_rpc,
    )


def _read_metadata(path: Path) -> dict[str, Any] | str | None:
    return read_metadata(path)


def _try_health_rpc(socket_path: Path) -> dict[str, Any]:
    return try_health_rpc(socket_path)


def _run_daemon_start(
    args: argparse.Namespace,
    *,
    popen: PopenFactory = _actions.subprocess.Popen,
    sleep: SleepFn = time.sleep,
) -> int:
    return run_daemon_start(
        args,
        popen=popen,
        sleep=sleep,
        prepare_daemon_launch=_prepare_daemon_launch,
        background_start_waiter=_wait_for_background_start,
        terminate_process=_terminate_process,
    )


def _run_daemon_stop(
    args: argparse.Namespace,
    *,
    kill: KillFn = _actions.os.kill,
    sleep: SleepFn = time.sleep,
) -> int:
    return run_daemon_stop(
        args,
        kill=kill,
        sleep=sleep,
        inspect_daemon=_inspect_daemon,
        process_is_live=_process_is_live,
        executable_matches_metadata=_executable_matches_metadata,
    )


def _run_daemon_rebuild(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_rebuild(
        args,
        inspect_daemon=_inspect_daemon,
        prepare_daemon_launch=_prepare_daemon_launch,
    )


def _repair_stale_lock(args: argparse.Namespace) -> dict[str, Any]:
    return repair_stale_lock(args, inspect_daemon=_inspect_daemon)


def _run_daemon_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_checkpoint(args, inspect_daemon=_inspect_daemon)


def _run_daemon_backup(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_backup(args, inspect_daemon=_inspect_daemon)


def _run_daemon_list_backups(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_list_backups(args, inspect_daemon=_inspect_daemon)


def _run_daemon_restore(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_restore(args, inspect_daemon=_inspect_daemon)


def _run_daemon_verify(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_verify(args, inspect_daemon=_inspect_daemon)


def _run_daemon_diff(args: argparse.Namespace) -> dict[str, Any]:
    return run_daemon_diff(args, inspect_daemon=_inspect_daemon)


def _wait_for_background_start(
    launch: _DaemonLaunch,
    proc: _actions.subprocess.Popen[Any],
    sleep: SleepFn,
) -> _DaemonInspection:
    return wait_for_background_start(
        launch,
        proc,
        sleep,
        inspect_daemon=_inspect_daemon,
    )


def _terminate_process(proc: _actions.subprocess.Popen[Any]) -> None:
    return _process.terminate_process(proc)


def _process_is_live(pid: int) -> bool:
    return _process.process_is_live(pid)


def _executable_matches_metadata(pid: int, metadata: dict[str, Any]) -> bool:
    return _process.executable_matches_metadata(pid, metadata)


def _print_status(inspection: _DaemonInspection) -> None:
    return print_status(inspection)


def _inspection_to_dict(inspection: _DaemonInspection) -> dict[str, Any]:
    return inspection_to_dict(inspection)


def _doctor_payload(inspection: _DaemonInspection) -> dict[str, Any]:
    return doctor_payload(inspection)
