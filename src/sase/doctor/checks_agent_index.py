"""Agent artifact index checks for ``sase doctor``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.agents.cli_index import build_agent_index_status_payload
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def agent_index_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default agent-index check specs."""
    return (
        CheckSpec(
            id="state.agent_index",
            group="state",
            title="Agent artifact index",
            runner=lambda: _check_agent_index(context),
        ),
    )


def _check_agent_index(context: DoctorContext) -> DiagnosticCheck:  # noqa: ARG001
    """Adapt the lightweight ``sase agent index status`` payload."""
    payload = build_agent_index_status_payload()
    repair_recommended = bool(payload.get("repair_recommended"))
    index_exists = bool(payload.get("index_exists"))
    visible_rows = int(payload.get("visible_rows") or 0)
    schema_version = int(payload.get("schema_version") or 0)

    status: CheckStatus = "WARN" if repair_recommended else "OK"
    if repair_recommended:
        reason = payload.get("repair_reason") or "unknown"
        summary = f"agent artifact index repair recommended: {reason}"
    else:
        summary = (
            f"schema {schema_version}; {visible_rows} visible row(s); "
            "no repair recommended"
        )

    details = _agent_index_details(payload)
    next_steps: tuple[str, ...] = ()
    if repair_recommended:
        next_steps = (
            f"Run `{payload.get('verify_command') or 'sase agent index verify'}`.",
            f"Repair with `{payload.get('repair_command') or 'sase agent index gc'}`.",
        )

    return DiagnosticCheck(
        id="state.agent_index",
        group="state",
        status=status,
        title="Agent artifact index",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={
            "index_path": payload.get("index_path"),
            "projects_root": payload.get("projects_root"),
            "index_exists": index_exists,
            "schema_version": schema_version,
            "visible_rows": visible_rows,
            "dismissed_projection_rows": payload.get("dismissed_projection_rows"),
            "complete_visible_inbox": payload.get("complete_visible_inbox"),
            "repair_recommended": repair_recommended,
            "repair_reason": payload.get("repair_reason"),
            "normal_refresh": payload.get("normal_refresh"),
        },
    )


def _agent_index_details(payload: dict[str, Any]) -> tuple[str, ...]:
    details = [
        f"index path: {payload.get('index_path')}",
        f"projects root: {payload.get('projects_root')}",
    ]
    reason = payload.get("repair_reason")
    if reason:
        details.append(f"repair reason: {reason}")
    return tuple(details)


__all__ = [
    "agent_index_check_specs",
]
