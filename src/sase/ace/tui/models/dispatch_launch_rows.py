"""Provisional Agents-list rows for source-side dispatch launches."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from ._fleet_agents_scalars import display_token, locator_id, mapping, optional_str
from .agent import Agent, AgentType

if TYPE_CHECKING:
    from sase.dispatch.launch import RemoteDispatchLaunchPreview


def dispatch_provisional_agent_from_preview(
    preview: RemoteDispatchLaunchPreview,
    *,
    prompt: str,
    payload: Mapping[str, object],
) -> Agent:
    """Build the immediate row shown while a dispatch launch is settling."""
    operation_key = dict(preview.operation_key)
    context = dict(preview.portable_context)
    logical_locator = dict(preview.provisional_locator)
    message = _source_context_message(context)
    return _agent_from_dispatch_parts(
        target=preview.target,
        target_installation_id=preview.target_installation_id,
        operation_key=operation_key,
        logical_locator=logical_locator,
        exact_locator={},
        context=context,
        prompt=prompt,
        payload=payload,
        status="QUEUED",
        dispatch_status="submitted",
        bounded_intent="accepted locally; waiting for owner",
        message=message,
    )


def dispatch_provisional_agent_from_payload(
    dispatch: Mapping[str, object],
    *,
    prompt: str | None = None,
    payload: Mapping[str, object] | None = None,
) -> Agent | None:
    """Build or update a provisional row from a durable launch result payload."""
    target = optional_str(dispatch.get("target"))
    operation_key = mapping(dispatch.get("operation_key"))
    operation_id = optional_str(operation_key.get("operation_id"))
    target_installation_id = optional_str(dispatch.get("target_installation_id"))
    if target is None or operation_id is None or target_installation_id is None:
        return None
    receipt = mapping(dispatch.get("receipt"))
    logical_locator = mapping(receipt.get("logical_locator"))
    exact_locator = mapping(receipt.get("instance_locator")) or mapping(
        receipt.get("exact_locator")
    )
    context = mapping(dispatch.get("portable_context"))
    source_status = optional_str(dispatch.get("source_status"), dispatch.get("state"))
    decision = optional_str(dispatch.get("decision"))
    reason = optional_str(dispatch.get("reason"), receipt.get("message"))
    status, dispatch_status, bounded_intent = _status_from_dispatch(
        source_status,
        decision,
    )
    message = reason or _source_context_message(context)
    return _agent_from_dispatch_parts(
        target=target,
        target_installation_id=target_installation_id,
        operation_key=dict(operation_key),
        logical_locator=dict(logical_locator),
        exact_locator=dict(exact_locator),
        context=dict(context),
        prompt=prompt,
        payload=payload,
        status=status,
        dispatch_status=dispatch_status,
        bounded_intent=bounded_intent,
        message=message,
    )


def dispatch_row_reconciled(
    provisional: Agent,
    rows: Sequence[Agent],
) -> bool:
    """Return whether a real fleet row supersedes *provisional*."""
    if not getattr(provisional, "fleet_dispatch_operation_key", None):
        return False
    provisional_ids = _row_reconciliation_ids(provisional)
    if not provisional_ids:
        return False
    for row in rows:
        if row is provisional:
            continue
        if not getattr(row, "fleet_origin_alias", None):
            continue
        if _row_reconciliation_ids(row) & provisional_ids:
            return True
    return False


def dispatch_operation_id(agent: Agent) -> str | None:
    """Return the provisional dispatch operation id for *agent*, if any."""
    key = getattr(agent, "fleet_dispatch_operation_key", None)
    if not isinstance(key, Mapping):
        return None
    return optional_str(key.get("operation_id"))


def mark_dispatch_row_unknown(agent: Agent, message: str) -> None:
    """Mark a provisional row as needing explicit outcome reconciliation."""
    agent.status = "WAITING"
    agent.status_bucket = "Waiting"
    agent.fleet_bounded_intent = "submission outcome unknown; check outcome"
    agent.fleet_dispatch_status = "outcome_unknown"
    agent.fleet_dispatch_message = message
    agent.fleet_diagnostic = message


def mark_dispatch_row_checking(agent: Agent) -> None:
    """Mark a provisional row while a check-outcome request is running."""
    agent.status = "WAITING"
    agent.status_bucket = "Waiting"
    agent.fleet_bounded_intent = "checking outcome"
    agent.fleet_dispatch_status = "checking"


def _agent_from_dispatch_parts(
    *,
    target: str,
    target_installation_id: str,
    operation_key: dict[str, Any],
    logical_locator: dict[str, Any],
    exact_locator: dict[str, Any],
    context: dict[str, Any],
    prompt: str | None,
    payload: Mapping[str, object] | None,
    status: str,
    dispatch_status: str,
    bounded_intent: str,
    message: str,
) -> Agent:
    operation_id = optional_str(operation_key.get("operation_id")) or "dispatch"
    logical_key = locator_id(logical_locator) if logical_locator else None
    exact_key = locator_id(exact_locator) if exact_locator else None
    agent_name = _agent_name(logical_locator, operation_id)
    project_id = _project_id(logical_locator, context)
    project_file = f"/fleet/{display_token(project_id)}/project.yml"
    raw = f"dispatch:{target}:{operation_id}"
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=display_token(project_id),
        project_file=project_file,
        status=status,
        status_bucket=_status_bucket(status),
        start_time=None,
        raw_suffix=raw,
        agent_name=agent_name,
        project_display_name=display_token(project_id),
        fleet_origin_alias=target,
        fleet_origin_installation_id=target_installation_id,
        fleet_logical_locator=logical_locator or None,
        fleet_exact_locator=exact_locator or None,
        fleet_logical_key=logical_key,
        fleet_exact_key=exact_key,
        fleet_connection_health="submission pending",
        fleet_freshness=dispatch_status,
        fleet_bounded_intent=bounded_intent,
        fleet_diagnostic=message,
        fleet_dispatch_operation_key=operation_key,
        fleet_dispatch_status=dispatch_status,
        fleet_dispatch_message=message,
        fleet_dispatch_prompt=prompt,
        fleet_dispatch_payload=dict(payload) if isinstance(payload, Mapping) else None,
    )
    return agent


def _status_from_dispatch(
    source_status: str | None,
    decision: str | None,
) -> tuple[str, str, str]:
    token = (source_status or decision or "accepted").casefold()
    if token in {"failed", "rejected", "reject", "refused"} or (
        decision and decision.casefold().startswith("reject")
    ):
        return "FAILED", "rejected", "rejected by owner"
    if token == "settled":
        return "STARTING", "settled", "owner accepted; waiting for row"
    if token in {"accepted", "accept_new", "return_original_receipt"}:
        return "QUEUED", "accepted", "owner accepted; waiting for row"
    return "WAITING", token, "submission outcome unknown; check outcome"


def _source_context_message(context: Mapping[str, Any]) -> str:
    patch_ref = optional_str(context.get("patch_ref"))
    if patch_ref:
        return f"source patch {patch_ref}"
    revision = optional_str(context.get("revision"))
    if revision:
        return f"source rev {revision[:12]}"
    project_id = optional_str(context.get("project_id"))
    return f"source {project_id}" if project_id else "source accepted"


def _agent_name(locator: Mapping[str, Any], operation_id: str) -> str:
    agent_id = optional_str(locator.get("agent_id"))
    return display_token(agent_id or operation_id)


def _project_id(
    locator: Mapping[str, Any],
    context: Mapping[str, Any],
) -> str:
    project = locator.get("project")
    if isinstance(project, Mapping):
        project_id = optional_str(project.get("project_id"))
        if project_id:
            return project_id
    return optional_str(context.get("project_id")) or "fleet"


def _status_bucket(status: str) -> str:
    if status == "FAILED":
        return "Failed"
    if status == "STARTING":
        return "Starting"
    if status == "QUEUED":
        return "Queued"
    return "Waiting"


def _row_reconciliation_ids(agent: Agent) -> set[str]:
    ids: set[str] = set()
    for value in (
        getattr(agent, "fleet_logical_key", None),
        getattr(agent, "fleet_exact_key", None),
    ):
        if isinstance(value, str) and value:
            ids.add(value)
    for locator in (
        getattr(agent, "fleet_logical_locator", None),
        getattr(agent, "fleet_exact_locator", None),
    ):
        if isinstance(locator, Mapping) and locator:
            ids.add(locator_id(locator))
    return ids


__all__ = [
    "dispatch_operation_id",
    "dispatch_provisional_agent_from_payload",
    "dispatch_provisional_agent_from_preview",
    "dispatch_row_reconciled",
    "mark_dispatch_row_checking",
    "mark_dispatch_row_unknown",
]
