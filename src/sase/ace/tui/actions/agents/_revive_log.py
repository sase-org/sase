"""Audit logging helpers for the agent revive flow.

Emits ``agent_revive_started``, ``agent_revived``, and ``agent_revive_failed``
events via ``sase.logs.run_log.log_event`` so the post-mortem question
"what agent did I last try to revive?" can be answered without grepping
through bundle directories that have already been deleted.

A broken log writer must never break a revival — every helper here wraps
the underlying ``log_event`` call in a broad ``except`` and silently
discards the error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import SelectionItem


EVENT_STARTED = "agent_revive_started"
EVENT_SUCCESS = "agent_revived"
EVENT_FAILURE = "agent_revive_failed"

_ERROR_MESSAGE_TRUNCATE = 500


def _agent_fields(agent: Agent) -> dict[str, Any]:
    """Common identity fields recorded for every per-agent event."""
    return {
        "agent_identity": [
            agent.agent_type.value,
            agent.cl_name,
            agent.raw_suffix,
        ],
        "agent_type": agent.agent_type.value,
        "cl_name": agent.cl_name,
        "raw_suffix": agent.raw_suffix,
        "project_file": agent.project_file,
        "bundle_path": getattr(agent, "_dismissed_bundle_path", None),
    }


def _scope_fields(scope: SelectionItem | None) -> dict[str, Any]:
    """Selection scope fields, when known."""
    if scope is None:
        return {}
    out: dict[str, Any] = {"selection_scope": scope.item_type}
    if scope.project_name:
        out["selection_project"] = scope.project_name
    if scope.cl_name:
        out["selection_cl"] = scope.cl_name
    return out


def log_revive_started(
    *,
    agents: list[Agent],
    selection_scope: SelectionItem | None = None,
) -> None:
    """Emit ``agent_revive_started`` for a single or batch revival.

    Captures user intent before any mutation, so a crash mid-revival
    still leaves a record of what was attempted.
    """
    try:
        from sase.logs.run_log import log_event

        identities = [
            [agent.agent_type.value, agent.cl_name, agent.raw_suffix]
            for agent in agents
        ]
        kwargs: dict[str, Any] = {
            "batch_size": len(agents),
            "agents": identities,
        }
        kwargs.update(_scope_fields(selection_scope))
        log_event(event=EVENT_STARTED, **kwargs)
    except Exception:
        pass


def log_revive_success(
    *,
    agent: Agent,
    child_suffixes: set[str] | None = None,
    batch_size: int = 1,
    selection_scope: SelectionItem | None = None,
) -> None:
    """Emit ``agent_revived`` for one successfully revived agent."""
    try:
        from sase.logs.run_log import log_event

        kwargs: dict[str, Any] = _agent_fields(agent)
        kwargs["child_suffixes"] = sorted(child_suffixes or set())
        kwargs["batch_size"] = batch_size
        kwargs["outcome"] = "success"
        kwargs.update(_scope_fields(selection_scope))
        log_event(event=EVENT_SUCCESS, **kwargs)
    except Exception:
        pass


def log_revive_failure(
    *,
    stage: str,
    agent: Agent | None = None,
    error: BaseException | None = None,
    reason: str | None = None,
    batch_size: int = 1,
    selection_scope: SelectionItem | None = None,
) -> None:
    """Emit ``agent_revive_failed`` for a failed (or skipped) revival.

    ``stage`` is one of ``dismissed_set_update``, ``artifact_restore``,
    ``bundle_removal``, ``reload``, ``refresh_display``, or
    ``no_dismissed_agents``. ``reason`` is used when there is no
    exception to attach (for example, the "no dismissed agents" early
    out).
    """
    try:
        from sase.logs.run_log import log_event

        kwargs: dict[str, Any] = {
            "stage": stage,
            "outcome": "failure",
            "batch_size": batch_size,
        }
        if agent is not None:
            kwargs.update(_agent_fields(agent))
        if error is not None:
            kwargs["error_type"] = type(error).__name__
            kwargs["error_message"] = str(error)[:_ERROR_MESSAGE_TRUNCATE]
        if reason is not None:
            kwargs["reason"] = reason
        kwargs.update(_scope_fields(selection_scope))
        log_event(event=EVENT_FAILURE, **kwargs)
    except Exception:
        pass
