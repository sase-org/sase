"""Status and doctor rendering for daemon lifecycle commands."""

from __future__ import annotations

import shlex
from typing import Any

from sase.daemon.paths import storage_layout_diagnostics
from sase.integrations._daemon_lifecycle_config import host_identity_from_env
from sase.integrations._daemon_lifecycle_health_details import (
    indexing_check_message,
    indexing_check_state,
    metadata_check_state,
    mobile_http_check_message,
    mobile_http_check_state,
    process_check_message,
    projection_check_message,
    projection_check_state,
    projection_details,
    rpc_check_message,
    rpc_check_state,
    scheduler_check_message,
    scheduler_check_state,
    scheduler_details,
    source_exports_check_message,
    source_exports_check_state,
    worst_check_state,
)
from sase.integrations._daemon_lifecycle_types import DaemonInspection


def print_status(inspection: DaemonInspection) -> None:
    print(f"SASE daemon status: {inspection.state}")
    print(f"Run root: {inspection.paths.run_root}")
    print(f"Socket: {inspection.paths.socket_path}")
    print(f"Log: {inspection.log_path}")
    layout = _storage_layout(inspection)
    warnings = layout.get("warnings", [])
    if warnings:
        print(f"Storage layout warnings: {len(warnings)}")
    if inspection.metrics_endpoint:
        print(f"Metrics: {inspection.metrics_endpoint}")
    if inspection.metadata is not None:
        pid = inspection.metadata.get("pid")
        hostname = inspection.metadata.get("hostname")
        started_at = inspection.metadata.get("started_at")
        build = inspection.metadata.get("build_version")
        print(f"PID: {pid}")
        print(f"Host: {hostname}")
        print(f"Started: {started_at}")
        print(f"Build: {build}")
    if inspection.message:
        print(f"Detail: {inspection.message}")
    if inspection.rpc is not None:
        print(f"RPC: {inspection.rpc.get('message') or inspection.rpc}")
    scheduler = scheduler_details(inspection)
    if scheduler is not None:
        print(
            "Scheduler: {state} queued={queued} running={running} "
            "starting={starting} blocked={blocked} stale={stale}".format(
                state=scheduler.get("state", "unknown"),
                queued=scheduler.get("queue_depth", 0),
                running=scheduler.get("running_tasks", 0),
                starting=scheduler.get("starting_tasks", 0),
                blocked=scheduler.get("blocked_tasks", 0),
                stale=scheduler.get("stale_starts", 0),
            )
        )


def inspection_to_dict(inspection: DaemonInspection) -> dict[str, Any]:
    return {
        "state": inspection.state,
        "sase_home": str(inspection.paths.sase_home),
        "run_root": str(inspection.paths.run_root),
        "socket_path": str(inspection.paths.socket_path),
        "projection_db_path": str(inspection.projection_db_path),
        "lock_path": str(inspection.lock_path),
        "metadata_path": str(inspection.paths.metadata_path),
        "log_path": str(inspection.log_path),
        "storage_layout": _storage_layout(inspection),
        "metrics_endpoint": inspection.metrics_endpoint,
        "metadata": inspection.metadata,
        "message": inspection.message,
        "rpc": inspection.rpc,
    }


def doctor_payload(inspection: DaemonInspection) -> dict[str, Any]:
    checks = [
        _check(
            "storage_layout",
            _storage_layout_check_state(inspection),
            _storage_layout_check_message(inspection),
        ),
        _check(
            "lock_metadata",
            metadata_check_state(inspection),
            inspection.message or "ownership metadata parsed",
        ),
        _check(
            "process_liveness",
            "ok" if inspection.state == "running" else inspection.state,
            process_check_message(inspection),
        ),
        _check(
            "socket_rpc_health",
            rpc_check_state(inspection),
            rpc_check_message(inspection),
        ),
        _check(
            "projection_db",
            projection_check_state(inspection),
            projection_check_message(inspection),
        ),
        _check(
            "source_exports",
            source_exports_check_state(inspection),
            source_exports_check_message(inspection),
        ),
        _check(
            "indexing",
            indexing_check_state(inspection),
            indexing_check_message(inspection),
        ),
        _check(
            "scheduler",
            scheduler_check_state(inspection),
            scheduler_check_message(inspection),
        ),
        _check(
            "mobile_http",
            mobile_http_check_state(inspection),
            mobile_http_check_message(inspection),
        ),
    ]
    doctor_state = worst_check_state(check["state"] for check in checks)
    repair_actions = _repair_actions(inspection)
    payload = inspection_to_dict(inspection)
    payload["repair_actions"] = repair_actions
    payload["doctor"] = {
        "state": doctor_state,
        "checks": checks,
        "repair_actions": repair_actions,
    }
    return payload


def _check(name: str, state: str, message: str) -> dict[str, str]:
    return {"name": name, "state": state, "message": message}


def _repair_actions(inspection: DaemonInspection) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    layout = _storage_layout(inspection)
    warnings = layout.get("warnings", [])
    has_layout_error = False
    if isinstance(warnings, list):
        for warning in warnings:
            if isinstance(warning, dict) and warning.get("severity") == "error":
                has_layout_error = True
                actions.append(
                    _repair_action(
                        "move_run_root",
                        None,
                        "requires_manual_review",
                        (
                            "Move daemon runtime files to a host-local run_root, "
                            "then exclude ~/.sase/run/ from sync."
                        ),
                    )
                )
                break

    if inspection.state == "stopped":
        if not has_layout_error:
            actions.append(
                _repair_action(
                    "daemon_start",
                    _daemon_command("start", inspection),
                    "runtime_only",
                    "Start the local daemon for live projection reads and maintenance.",
                )
            )
    elif inspection.state == "running":
        actions.extend(
            [
                _repair_action(
                    "daemon_verify",
                    _daemon_command("verify", inspection),
                    "read_only",
                    "Verify daemon projections against source stores.",
                ),
                _repair_action(
                    "daemon_stop",
                    _daemon_command("stop", inspection),
                    "runtime_only",
                    "Stop the live daemon owned by this host.",
                ),
            ]
        )
        projection = projection_details(inspection)
        if isinstance(projection, dict) and (
            projection.get("repair_needed") or projection.get("state") == "degraded"
        ):
            actions.append(
                _repair_action(
                    "daemon_rebuild_reset_storage",
                    _daemon_command("rebuild", inspection, "--reset-storage"),
                    "runtime_only",
                    (
                        "Reset and replay daemon projection storage; source stores "
                        "are not modified."
                    ),
                )
            )
    elif inspection.state == "stale":
        actions.append(
            _repair_action(
                "remove_stale_lock",
                _daemon_command("doctor", inspection, "--repair-stale-lock"),
                "runtime_only",
                (
                    "Remove stale daemon lock, metadata, and host-local socket files "
                    "after confirming no live process owns the lock."
                ),
            )
        )
    elif inspection.state == "conflict":
        actions.append(
            _repair_action(
                "inspect_host_conflict",
                _daemon_command("status", inspection, "--json"),
                "requires_manual_review",
                (
                    "Inspect ownership metadata before changing anything; different-host "
                    "or live PID conflicts are never repaired automatically."
                ),
            )
        )
    elif inspection.state == "incompatible":
        actions.append(
            _repair_action(
                "inspect_host_conflict",
                _daemon_command("status", inspection, "--json"),
                "requires_manual_review",
                "Inspect incompatible daemon ownership metadata manually.",
            )
        )
    return _dedupe_actions(actions)


def _repair_action(
    action_id: str,
    command: str | None,
    risk: str,
    explanation: str,
) -> dict[str, str]:
    payload = {
        "id": action_id,
        "risk": risk,
        "explanation": explanation,
    }
    if command:
        payload["command"] = command
    return payload


def _daemon_command(
    subcommand: str,
    inspection: DaemonInspection,
    *extra: str,
) -> str:
    parts = [
        "sase",
        "daemon",
        subcommand,
        "-H",
        str(inspection.paths.sase_home),
        "--run-root",
        str(inspection.paths.run_root),
        "--socket-path",
        str(inspection.paths.socket_path),
        *extra,
    ]
    return shlex.join(parts)


def _dedupe_actions(actions: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for action in actions:
        action_id = action["id"]
        if action_id in seen:
            continue
        seen.add(action_id)
        result.append(action)
    return result


def _storage_layout(inspection: DaemonInspection) -> dict[str, Any]:
    return storage_layout_diagnostics(
        sase_home=inspection.paths.sase_home,
        run_root=inspection.paths.run_root,
        socket_path=inspection.paths.socket_path,
        host_identity=_layout_host_identity(inspection),
    )


def _layout_host_identity(inspection: DaemonInspection) -> str:
    metadata_host = (inspection.metadata or {}).get("hostname")
    if isinstance(metadata_host, str) and metadata_host:
        return metadata_host
    return host_identity_from_env()


def _storage_layout_check_state(inspection: DaemonInspection) -> str:
    warnings = _storage_layout(inspection).get("warnings", [])
    if not isinstance(warnings, list) or not warnings:
        return "ok"
    has_error = any(
        isinstance(warning, dict) and warning.get("severity") == "error"
        for warning in warnings
    )
    return "error" if has_error else "degraded"


def _storage_layout_check_message(inspection: DaemonInspection) -> str:
    layout = _storage_layout(inspection)
    warnings = layout.get("warnings", [])
    if not isinstance(warnings, list) or not warnings:
        return "runtime files are under the host-local layout"
    ids = [
        str(warning.get("id"))
        for warning in warnings
        if isinstance(warning, dict) and warning.get("id")
    ]
    return "layout warnings: " + ", ".join(ids)
