"""Backend selection and parity helpers for agent composition."""

import logging
import os

from sase.core.agent_compose_wire import (
    AgentComposeInputWire,
    ComposedAgentListWire,
    composed_agent_list_to_json_dict,
)

from ..util.trace import trace_event
from .agent import Agent, AgentType

log = logging.getLogger(__name__)

_AGENT_COMPOSE_SHADOW_ENV = "SASE_AGENT_COMPOSE_SHADOW"
_AGENT_COMPOSE_BENCH_ENV = "SASE_AGENT_COMPOSE_BENCH"
_AGENT_COMPOSE_BACKEND_ENV = "SASE_AGENT_COMPOSE_BACKEND"
_AGENT_COMPOSE_BACKENDS = frozenset({"python", "rust"})


def dismissed_from_agents(
    agents: list[Agent],
    dismissed_agents: set[tuple[AgentType, str, str | None]] | None,
) -> list[Agent]:
    if not dismissed_agents:
        return []
    dismissed_suffixes = {
        raw_suffix for _, _, raw_suffix in dismissed_agents if raw_suffix is not None
    }
    return [
        agent
        for agent in agents
        if agent.status != "RUNNING"
        and (
            agent.identity in dismissed_agents
            or (agent.raw_suffix is not None and agent.raw_suffix in dismissed_suffixes)
        )
    ]


def _agent_compose_shadow_enabled() -> bool:
    return (
        os.environ.get(_AGENT_COMPOSE_SHADOW_ENV) == "1"
        or os.environ.get(_AGENT_COMPOSE_BENCH_ENV) == "1"
    )


def agent_compose_backend() -> str:
    backend = os.environ.get(_AGENT_COMPOSE_BACKEND_ENV, "rust").strip().lower()
    if backend not in _AGENT_COMPOSE_BACKENDS:
        expected = ", ".join(sorted(_AGENT_COMPOSE_BACKENDS))
        raise ValueError(
            f"Unsupported {_AGENT_COMPOSE_BACKEND_ENV}={backend!r}; "
            f"expected one of: {expected}."
        )
    return backend


def _comparison_payload(record: ComposedAgentListWire) -> dict[str, object]:
    payload = composed_agent_list_to_json_dict(record)
    return {
        "agents": payload["agents"],
        "workflow_agent_steps": payload["workflow_agent_steps"],
        "dismissed_from_loader": payload["dismissed_from_loader"],
    }


def shadow_compare_agent_compose(
    compose_input: AgentComposeInputWire,
    agents: list[Agent],
    workflow_agent_steps: list[Agent],
    dismissed_from_loader: list[Agent],
) -> None:
    if not _agent_compose_shadow_enabled():
        return

    from sase.core.agent_compose_facade import (
        compose_agent_list,
        compose_python_agents_to_wire,
    )

    python_wire = compose_python_agents_to_wire(
        agents,
        workflow_agent_steps=workflow_agent_steps,
        dismissed_from_loader=dismissed_from_loader,
    )
    try:
        rust_wire = compose_agent_list(compose_input)
    except Exception as exc:
        log.debug("agent compose shadow call failed: %s", exc)
        trace_event("agent_compose.shadow", ok=False, error=type(exc).__name__)
        return

    python_payload = _comparison_payload(python_wire)
    rust_payload = _comparison_payload(rust_wire)
    ok = python_payload == rust_payload
    if not ok:
        log.debug(
            "agent compose shadow parity mismatch: python=%r rust=%r",
            python_payload,
            rust_payload,
        )
    trace_event(
        "agent_compose.shadow",
        ok=ok,
        python_agents=len(python_wire.agents),
        rust_agents=len(rust_wire.agents),
        rust_dropped=len(rust_wire.dropped),
        rust_merge_log=len(rust_wire.merge_log),
    )


def compose_rust_agent_list_with_dismissed(
    compose_input: AgentComposeInputWire,
) -> tuple[list[Agent], list[Agent]]:
    from sase.core.agent_compose_facade import (
        compose_agent_list,
        composed_agent_list_to_agents,
        composed_agent_list_to_dismissed_agents,
    )

    record = compose_agent_list(compose_input)
    return (
        composed_agent_list_to_agents(record),
        composed_agent_list_to_dismissed_agents(record),
    )
