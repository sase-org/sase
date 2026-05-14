"""CLI handlers for daemon lifecycle commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any


def handle_daemon_start(args: argparse.Namespace) -> int:
    """CLI wrapper for ``sase daemon start``."""
    lifecycle = _lifecycle()
    try:
        return lifecycle._run_daemon_start(args)
    except lifecycle._DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def handle_daemon_status(args: argparse.Namespace) -> int:
    """CLI wrapper for ``sase daemon status``."""
    lifecycle = _lifecycle()
    inspection = lifecycle._inspect_daemon(args)
    if getattr(args, "json_output", False):
        print(
            json.dumps(
                lifecycle._inspection_to_dict(inspection), indent=2, sort_keys=True
            )
        )
    else:
        lifecycle._print_status(inspection)
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
    lifecycle = _lifecycle()
    try:
        return lifecycle._run_daemon_stop(args)
    except lifecycle._DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def handle_daemon_doctor(args: argparse.Namespace) -> int:
    """Run daemon lifecycle and projection diagnostics."""
    lifecycle = _lifecycle()
    if getattr(args, "repair_stale_lock", False):
        try:
            repair_payload = lifecycle._repair_stale_lock(args)
        except lifecycle._DaemonLifecycleError as exc:
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
    inspection = lifecycle._inspect_daemon(args)
    payload = lifecycle._doctor_payload(inspection)
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        lifecycle._print_status(inspection)
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
                print(
                    "- {id}: {risk} - {explanation}".format(
                        id=action.get("id", "unknown"),
                        risk=action.get("risk", "unknown"),
                        explanation=action.get("explanation", ""),
                    )
                )
                if command:
                    print(f"  Command: {command}")
    return 0


def handle_daemon_rebuild(args: argparse.Namespace) -> int:
    """Rebuild daemon projections through a live daemon or one-shot Rust path."""
    lifecycle = _lifecycle()
    try:
        payload = lifecycle._run_daemon_rebuild(args)
    except lifecycle._DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_rebuild_payload(payload)
    return 0


def handle_daemon_checkpoint(args: argparse.Namespace) -> int:
    """Checkpoint the projection WAL through a live daemon."""
    lifecycle = _lifecycle()
    try:
        payload = lifecycle._run_daemon_checkpoint(args)
    except lifecycle._DaemonLifecycleError as exc:
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
    lifecycle = _lifecycle()
    try:
        payload = lifecycle._run_daemon_backup(args)
    except lifecycle._DaemonLifecycleError as exc:
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
    lifecycle = _lifecycle()
    try:
        payload = lifecycle._run_daemon_list_backups(args)
    except lifecycle._DaemonLifecycleError as exc:
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
    lifecycle = _lifecycle()
    try:
        payload = lifecycle._run_daemon_restore(args)
    except lifecycle._DaemonLifecycleError as exc:
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
    lifecycle = _lifecycle()
    try:
        payload = lifecycle._run_daemon_verify(args)
    except lifecycle._DaemonLifecycleError as exc:
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
    lifecycle = _lifecycle()
    try:
        payload = lifecycle._run_daemon_diff(args)
    except lifecycle._DaemonLifecycleError as exc:
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


def _print_rebuild_payload(payload: dict[str, Any]) -> None:
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
    _print_source_exports(payload)
    for summary in payload.get("summaries", []):
        if isinstance(summary, dict):
            _print_indexing_summary(summary)
    if payload.get("next_command"):
        print(f"Next: {payload['next_command']}")


def _print_source_exports(payload: dict[str, Any]) -> None:
    source_exports = payload.get("source_exports")
    if not isinstance(source_exports, dict):
        return
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

    lifecycle = _lifecycle()
    inspection = lifecycle._inspect_daemon(args)
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

    lifecycle = _lifecycle()
    inspection = lifecycle._inspect_daemon(args)
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


def _lifecycle() -> Any:
    from sase.integrations import daemon_lifecycle

    return daemon_lifecycle
