"""Telemetry checks for ``sase doctor``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.telemetry.cli_health import build_telemetry_health_payload
from sase.telemetry.cli_status import build_telemetry_status_payload

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_TELEMETRY_TIMEOUT_SECONDS = 1.0


def telemetry_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default and deep telemetry check specs."""
    del context
    return (
        CheckSpec(
            id="ops.telemetry_status",
            group="ops",
            title="Telemetry status",
            runner=_check_telemetry_status,
        ),
        CheckSpec(
            id="ops.telemetry_health",
            group="ops",
            title="Telemetry health",
            runner=_check_telemetry_health,
            deep=True,
        ),
    )


def _check_telemetry_status() -> DiagnosticCheck:
    """Check telemetry enablement, local store access, and write freshness."""
    payload = build_telemetry_status_payload(timeout=_TELEMETRY_TIMEOUT_SECONDS)
    if not bool(payload.get("enabled")):
        return DiagnosticCheck(
            id="ops.telemetry_status",
            group="ops",
            status="SKIP",
            title="Telemetry status",
            summary="telemetry is disabled",
            data=payload,
        )

    raw_store = payload.get("store")
    store: dict[str, Any] = raw_store if isinstance(raw_store, dict) else {}
    raw_flusher = payload.get("flusher")
    flusher: dict[str, Any] = raw_flusher if isinstance(raw_flusher, dict) else {}
    store_error = payload.get("store_error")
    flusher_state = str(flusher.get("state") or "idle")
    status: CheckStatus = (
        "WARN" if store_error or flusher_state in {"error", "stale"} else "OK"
    )
    metric_count = int(payload.get("metric_count") or 0)
    sample_count = int(store.get("sample_count") or 0)
    summary = (
        f"telemetry enabled; {metric_count} metric(s); {sample_count} local sample(s)"
    )
    details_list: list[str] = []
    if store_error:
        details_list.append(f"local telemetry store error: {store_error}")
    if flusher_state == "stale":
        details_list.append("the local telemetry store has not received a recent write")
    details = tuple(details_list)

    return DiagnosticCheck(
        id="ops.telemetry_status",
        group="ops",
        status=status,
        title="Telemetry status",
        summary=summary,
        details=details,
        next_steps=("Run `sase telemetry status`.",) if status == "WARN" else (),
        data=payload,
    )


def _check_telemetry_health() -> DiagnosticCheck:
    """Adapt deep local-store health into one doctor check."""
    status_payload = build_telemetry_status_payload(timeout=_TELEMETRY_TIMEOUT_SECONDS)
    if not bool(status_payload.get("enabled")):
        return DiagnosticCheck(
            id="ops.telemetry_health",
            group="ops",
            status="SKIP",
            title="Telemetry health",
            summary="telemetry is disabled",
            data=status_payload,
        )

    payload = build_telemetry_health_payload("auto")
    raw_status = str(payload.get("status") or "error")
    if raw_status == "ok":
        status: CheckStatus = "OK"
    else:
        status = "WARN"

    subsystems = _subsystem_rows(payload)
    problem_subsystems = [
        row for row in subsystems if row["status"] not in {"ok", "OK"}
    ]
    details: tuple[str, ...]
    if raw_status == "no_data":
        summary = "the local telemetry store has no samples from the last hour"
        details = ()
    elif raw_status == "error":
        summary = "the local telemetry store could not be queried"
        details = (str(payload.get("error") or "unknown store error"),)
    else:
        summary = f"telemetry health status is {raw_status}"
        details = tuple(
            f"{row['name']}: {row['status']} ({row['detail']})"
            for row in problem_subsystems
        )

    return DiagnosticCheck(
        id="ops.telemetry_health",
        group="ops",
        status=status,
        title="Telemetry health",
        summary=summary,
        details=details,
        next_steps=("Run `sase telemetry health -j`.",) if status == "WARN" else (),
        data=payload,
    )


def _subsystem_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw = payload.get("subsystems")
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "name": str(item.get("name", "")),
                "status": str(item.get("status", "")),
                "detail": str(item.get("detail", "")),
            }
        )
    return rows


__all__ = [
    "telemetry_check_specs",
]
