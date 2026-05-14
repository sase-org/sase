"""Status and doctor rendering for daemon lifecycle commands."""

from __future__ import annotations

from typing import Any

from sase.integrations._daemon_lifecycle_types import DaemonInspection


def print_status(inspection: DaemonInspection) -> None:
    print(f"SASE daemon status: {inspection.state}")
    print(f"Run root: {inspection.paths.run_root}")
    print(f"Socket: {inspection.paths.socket_path}")
    print(f"Log: {inspection.log_path}")
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


def inspection_to_dict(inspection: DaemonInspection) -> dict[str, Any]:
    return {
        "state": inspection.state,
        "sase_home": str(inspection.paths.sase_home),
        "run_root": str(inspection.paths.run_root),
        "socket_path": str(inspection.paths.socket_path),
        "metadata_path": str(inspection.paths.metadata_path),
        "log_path": str(inspection.log_path),
        "metrics_endpoint": inspection.metrics_endpoint,
        "metadata": inspection.metadata,
        "message": inspection.message,
        "rpc": inspection.rpc,
    }


def doctor_payload(inspection: DaemonInspection) -> dict[str, Any]:
    checks = [
        _check(
            "lock_metadata",
            _metadata_check_state(inspection),
            inspection.message or "ownership metadata parsed",
        ),
        _check(
            "process_liveness",
            "ok" if inspection.state == "running" else inspection.state,
            _process_check_message(inspection),
        ),
        _check(
            "socket_rpc_health",
            _rpc_check_state(inspection),
            _rpc_check_message(inspection),
        ),
        _check(
            "projection_db",
            _projection_check_state(inspection),
            _projection_check_message(inspection),
        ),
        _check(
            "mobile_http",
            _mobile_http_check_state(inspection),
            _mobile_http_check_message(inspection),
        ),
    ]
    doctor_state = _worst_check_state(check["state"] for check in checks)
    payload = inspection_to_dict(inspection)
    payload["doctor"] = {"state": doctor_state, "checks": checks}
    return payload


def _check(name: str, state: str, message: str) -> dict[str, str]:
    return {"name": name, "state": state, "message": message}


def _metadata_check_state(inspection: DaemonInspection) -> str:
    if inspection.state in {"running", "stale", "stopped"}:
        return inspection.state if inspection.state != "running" else "ok"
    return "error"


def _process_check_message(inspection: DaemonInspection) -> str:
    if inspection.state == "running":
        pid = (inspection.metadata or {}).get("pid")
        return f"metadata pid {pid} is live"
    return inspection.message or f"daemon is {inspection.state}"


def _rpc_check_state(inspection: DaemonInspection) -> str:
    if inspection.state != "running":
        return "skipped"
    if not inspection.rpc or not inspection.rpc.get("available"):
        return "error"
    health = inspection.rpc.get("health")
    if isinstance(health, dict) and health.get("status") == "degraded":
        return "degraded"
    return "ok"


def _rpc_check_message(inspection: DaemonInspection) -> str:
    if inspection.state != "running":
        return "daemon is not running"
    if not inspection.rpc:
        return "local RPC was not checked"
    if not inspection.rpc.get("available"):
        return str(inspection.rpc.get("message") or "local RPC unavailable")
    health = inspection.rpc.get("health")
    if isinstance(health, dict):
        return f"health status {health.get('status', 'unknown')}"
    return "local RPC health is available"


def _projection_check_state(inspection: DaemonInspection) -> str:
    projection = _projection_details(inspection)
    if projection is None:
        return "skipped" if inspection.state != "running" else "unknown"
    state = projection.get("state")
    if state == "ok":
        return "ok"
    if state == "degraded":
        return "degraded"
    return "unknown"


def _projection_check_message(inspection: DaemonInspection) -> str:
    projection = _projection_details(inspection)
    if projection is None:
        return "projection health requires live daemon RPC"
    message = projection.get("message")
    if isinstance(message, str) and message:
        return message
    return (
        "schema_initialized={schema_initialized}, migrations_applied={migrations}, "
        "repair_needed={repair_needed}, gaps={gap_count}, recovery_issues={issues}"
    ).format(
        schema_initialized=projection.get("schema_initialized"),
        migrations=projection.get("migrations_applied"),
        repair_needed=projection.get("repair_needed"),
        gap_count=projection.get("gap_count"),
        issues=projection.get("recovery_issue_count"),
    )


def _projection_details(inspection: DaemonInspection) -> dict[str, Any] | None:
    rpc = inspection.rpc or {}
    health = rpc.get("health") if isinstance(rpc, dict) else None
    details = health.get("details") if isinstance(health, dict) else None
    projection = details.get("projection_db") if isinstance(details, dict) else None
    return projection if isinstance(projection, dict) else None


def _mobile_http_check_state(inspection: DaemonInspection) -> str:
    if inspection.state != "running":
        return "skipped"
    return "ok" if inspection.metrics_endpoint else "skipped"


def _mobile_http_check_message(inspection: DaemonInspection) -> str:
    if inspection.state != "running":
        return "daemon is not running"
    if inspection.metrics_endpoint:
        return f"loopback metrics endpoint: {inspection.metrics_endpoint}"
    return "mobile HTTP is disabled or metrics endpoint was not published"


def _worst_check_state(states: Any) -> str:
    order = {
        "error": 5,
        "conflict": 5,
        "incompatible": 5,
        "degraded": 4,
        "stale": 3,
        "unknown": 2,
        "skipped": 1,
        "stopped": 1,
        "ok": 0,
    }
    worst = "ok"
    worst_score = 0
    for state in states:
        score = order.get(str(state), 2)
        if score > worst_score:
            worst = str(state)
            worst_score = score
    return worst
