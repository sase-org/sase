"""Health check state and message helpers for daemon diagnostics."""

from __future__ import annotations

from typing import Any

from sase.integrations._daemon_lifecycle_types import DaemonInspection


def metadata_check_state(inspection: DaemonInspection) -> str:
    if inspection.state in {"running", "stale", "stopped"}:
        return inspection.state if inspection.state != "running" else "ok"
    return "error"


def process_check_message(inspection: DaemonInspection) -> str:
    if inspection.state == "running":
        pid = (inspection.metadata or {}).get("pid")
        return f"metadata pid {pid} is live"
    return inspection.message or f"daemon is {inspection.state}"


def rpc_check_state(inspection: DaemonInspection) -> str:
    if inspection.state != "running":
        return "skipped"
    if not inspection.rpc or not inspection.rpc.get("available"):
        return "error"
    health = inspection.rpc.get("health")
    if isinstance(health, dict) and health.get("status") == "degraded":
        return "degraded"
    return "ok"


def rpc_check_message(inspection: DaemonInspection) -> str:
    if inspection.state != "running":
        return "daemon is not running"
    if not inspection.rpc:
        return "local RPC was not checked"
    if not inspection.rpc.get("available"):
        return str(inspection.rpc.get("message") or "local RPC unavailable")
    health = inspection.rpc.get("health")
    if isinstance(health, dict):
        diagnostics = _diagnostics_unavailable(inspection)
        if diagnostics:
            return (
                f"health status {health.get('status', 'unknown')}; "
                f"detailed diagnostics unavailable: {diagnostics}"
            )
        return f"health status {health.get('status', 'unknown')}"
    return "local RPC health is available"


def projection_check_state(inspection: DaemonInspection) -> str:
    projection = projection_details(inspection)
    if projection is None:
        return "skipped" if inspection.state != "running" else "unknown"
    state = projection.get("state")
    if state == "ok":
        return "ok"
    if state == "degraded":
        return "degraded"
    return "unknown"


def projection_check_message(inspection: DaemonInspection) -> str:
    projection = projection_details(inspection)
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


def projection_details(inspection: DaemonInspection) -> dict[str, Any] | None:
    rpc = inspection.rpc or {}
    health = rpc.get("health") if isinstance(rpc, dict) else None
    details = health.get("details") if isinstance(health, dict) else None
    projection = details.get("projection_db") if isinstance(details, dict) else None
    return projection if isinstance(projection, dict) else None


def source_exports_check_state(inspection: DaemonInspection) -> str:
    source_exports = _source_exports_details(inspection)
    if source_exports is None:
        if inspection.state != "running":
            return "skipped"
        if _diagnostics_unavailable(inspection):
            return "unknown"
        return "ok" if projection_details(inspection) is not None else "unknown"
    state = source_exports.get("state")
    if state == "ok":
        return "ok"
    if state == "degraded":
        return "degraded"
    return "unknown"


def source_exports_check_message(inspection: DaemonInspection) -> str:
    source_exports = _source_exports_details(inspection)
    if source_exports is None:
        diagnostics = _diagnostics_unavailable(inspection)
        if diagnostics:
            return f"detailed source-export diagnostics unavailable: {diagnostics}"
        if projection_details(inspection) is not None:
            return "source-export diagnostics were not reported"
        return "source-export diagnostics require live daemon RPC"
    message = source_exports.get("message")
    if isinstance(message, str) and message:
        return message
    conflict_count = _int_or_zero(source_exports.get("conflict"))
    if conflict_count:
        examples = source_exports.get("examples")
        target = None
        if isinstance(examples, list):
            for example in examples:
                if isinstance(example, dict) and example.get("target_path"):
                    target = str(example["target_path"])
                    break
        detail = f"; first target: {target}" if target else ""
        return (
            f"{conflict_count} source export conflict(s) need manual review; "
            f"run `sase daemon diff --surface all --json`{detail}"
        )
    return ("pending={pending}, failed={failed}, conflicts={conflict}").format(
        pending=source_exports.get("pending", 0),
        failed=source_exports.get("failed", 0),
        conflict=source_exports.get("conflict", 0),
    )


def _source_exports_details(
    inspection: DaemonInspection,
) -> dict[str, Any] | None:
    projection = projection_details(inspection)
    if projection is None:
        return None
    source_exports = projection.get("source_exports")
    return source_exports if isinstance(source_exports, dict) else None


def indexing_check_state(inspection: DaemonInspection) -> str:
    indexing = _indexing_details(inspection)
    if indexing is None:
        return "skipped" if inspection.state != "running" else "unknown"
    state = indexing.get("state")
    if state in {"ok", "stopped"}:
        return "ok" if state == "ok" else "stopped"
    if state == "degraded":
        return "degraded"
    return "unknown"


def indexing_check_message(inspection: DaemonInspection) -> str:
    indexing = _indexing_details(inspection)
    if indexing is None:
        return "indexing health requires live daemon RPC"
    message = indexing.get("message")
    if isinstance(message, str) and message:
        return message
    return (
        "watcher_active={watcher_active}, queued={queued}, dropped={dropped}, "
        "indexed={indexed}, failed_parses={failed}"
    ).format(
        watcher_active=indexing.get("watcher_active"),
        queued=indexing.get("queued_changes"),
        dropped=indexing.get("dropped_changes"),
        indexed=indexing.get("indexed_sources"),
        failed=indexing.get("failed_parses"),
    )


def _indexing_details(inspection: DaemonInspection) -> dict[str, Any] | None:
    rpc = inspection.rpc or {}
    health = rpc.get("health") if isinstance(rpc, dict) else None
    details = health.get("details") if isinstance(health, dict) else None
    indexing = details.get("indexing") if isinstance(details, dict) else None
    return indexing if isinstance(indexing, dict) else None


def scheduler_check_state(inspection: DaemonInspection) -> str:
    scheduler = scheduler_details(inspection)
    if scheduler is None:
        if _diagnostics_unavailable(inspection):
            return "unknown"
        return "skipped" if inspection.state != "running" else "unknown"
    state = scheduler.get("state")
    if state == "ok":
        return "ok"
    if state == "degraded":
        return "degraded"
    return "unknown"


def scheduler_check_message(inspection: DaemonInspection) -> str:
    scheduler = scheduler_details(inspection)
    if scheduler is None:
        diagnostics = _diagnostics_unavailable(inspection)
        if diagnostics:
            return f"detailed scheduler diagnostics unavailable: {diagnostics}"
        return "scheduler health requires live daemon RPC"
    message = scheduler.get("message")
    if isinstance(message, str) and message:
        return message
    lag = scheduler.get("projection_lag")
    pending = lag.get("pending_events", 0) if isinstance(lag, dict) else 0
    bridge = scheduler.get("host_bridge")
    bridge_available = (
        bridge.get("available") if isinstance(bridge, dict) else "unknown"
    )
    return (
        "queued={queued}, running={running}, starting={starting}, "
        "blocked={blocked}, stale_starts={stale}, host_bridge={bridge}, "
        "projection_pending_events={pending}"
    ).format(
        queued=scheduler.get("queue_depth", 0),
        running=scheduler.get("running_tasks", 0),
        starting=scheduler.get("starting_tasks", 0),
        blocked=scheduler.get("blocked_tasks", 0),
        stale=scheduler.get("stale_starts", 0),
        bridge=bridge_available,
        pending=pending,
    )


def scheduler_details(inspection: DaemonInspection) -> dict[str, Any] | None:
    rpc = inspection.rpc or {}
    health = rpc.get("health") if isinstance(rpc, dict) else None
    details = health.get("details") if isinstance(health, dict) else None
    scheduler = details.get("scheduler") if isinstance(details, dict) else None
    return scheduler if isinstance(scheduler, dict) else None


def _diagnostics_unavailable(inspection: DaemonInspection) -> str | None:
    rpc = inspection.rpc or {}
    diagnostics = rpc.get("diagnostics") if isinstance(rpc, dict) else None
    if not isinstance(diagnostics, dict):
        return None
    if diagnostics.get("available") is not False:
        return None
    message = diagnostics.get("message")
    return str(message or "diagnostic health RPC failed")


def mobile_http_check_state(inspection: DaemonInspection) -> str:
    if inspection.state != "running":
        return "skipped"
    return "ok" if inspection.metrics_endpoint else "skipped"


def mobile_http_check_message(inspection: DaemonInspection) -> str:
    if inspection.state != "running":
        return "daemon is not running"
    if inspection.metrics_endpoint:
        return f"loopback metrics endpoint: {inspection.metrics_endpoint}"
    return "mobile HTTP is disabled or metrics endpoint was not published"


def worst_check_state(states: Any) -> str:
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


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
