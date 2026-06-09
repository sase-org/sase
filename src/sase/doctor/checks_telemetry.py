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
    """Check telemetry enablement and endpoint reachability."""
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

    endpoints = _endpoint_rows(payload)
    unreachable = [row for row in endpoints if row["reachable"] is False]
    status: CheckStatus = "WARN" if unreachable else "OK"
    metric_count = int(payload.get("metric_count") or 0)
    summary = (
        f"telemetry enabled; {metric_count} metric(s); endpoints reachable"
        if not unreachable
        else f"telemetry enabled but {len(unreachable)} endpoint(s) are unreachable"
    )
    details = tuple(
        f"{row['name']}: {row['url']} is not reachable" for row in unreachable
    )

    return DiagnosticCheck(
        id="ops.telemetry_status",
        group="ops",
        status=status,
        title="Telemetry status",
        summary=summary,
        details=details,
        next_steps=("Run `sase telemetry status`.",) if unreachable else (),
        data={**payload, "endpoints": endpoints},
    )


def _check_telemetry_health() -> DiagnosticCheck:
    """Adapt deep Prometheus health into one doctor check."""
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
    raw_status = str(payload.get("status") or "unreachable")
    if raw_status == "ok":
        status: CheckStatus = "OK"
    else:
        status = "WARN"

    subsystems = _subsystem_rows(payload)
    problem_subsystems = [
        row for row in subsystems if row["status"] not in {"ok", "OK"}
    ]
    details: tuple[str, ...]
    if raw_status == "unreachable":
        summary = "no telemetry metric source is reachable"
        details = ("pushgateway and exposition endpoints were not reachable",)
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


def _endpoint_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in ("pushgateway", "exposition"):
        raw = payload.get(name)
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "name": name,
                "url": raw.get("metrics_url"),
                "reachable": raw.get("reachable"),
            }
        )
    return rows


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
