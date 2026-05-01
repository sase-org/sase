"""Reference facade for agent-list composition.

Phase 1 intentionally keeps product behavior on the existing Python loader.
The helpers here expose that loader through the future Rust wire contract so
golden fixtures and benchmarks can compare subsequent implementations against
one stable shape.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_compose_wire import (
    AgentComposeInputWire,
    AgentComposeOptionsWire,
    ComposedAgentListWire,
    RunningClaimWire,
    agent_compose_wire_to_json_dict,
    agent_from_wire,
    agent_to_wire,
    composed_agent_list_from_dict,
)
from sase.core.agent_scan_wire import AgentArtifactScanWire
from sase.core.rust import require_rust_binding
from sase.core.wire import ChangeSpecWire

logger = logging.getLogger(__name__)


def compose_python_agents_to_wire(
    agents: list[Agent],
    *,
    workflow_agent_steps: list[Agent] | None = None,
    dismissed_from_loader: list[Agent] | None = None,
) -> ComposedAgentListWire:
    """Project already-composed Python agents into the compose wire shape."""

    return ComposedAgentListWire(
        agents=[agent_to_wire(agent) for agent in agents],
        workflow_agent_steps=[
            agent_to_wire(agent) for agent in (workflow_agent_steps or [])
        ],
        dismissed_from_loader=[
            agent_to_wire(agent) for agent in (dismissed_from_loader or [])
        ],
        dropped=[],
        merge_log=[],
    )


# pyvision: tests/test_core_agent_compose.py
def compose_agent_list_reference(
    input_wire: AgentComposeInputWire | None = None,
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
) -> ComposedAgentListWire:
    """Run the current Python loader and return the stable compose wire shape.

    ``input_wire`` is accepted to match the future Rust operation signature.
    Phase 1 does not route product code through these data inputs yet; it uses
    the established Python loader as the reference implementation.
    """

    from sase.ace.tui.models.agent_loader import load_all_agents

    agents = load_all_agents(changespec_snapshot=changespec_snapshot)
    if input_wire is not None and not input_wire.options.include_workflow_steps:
        return compose_python_agents_to_wire(agents)
    return compose_python_agents_to_wire(agents)


# pyvision: tests/test_core_agent_compose.py
def with_options(
    base: AgentComposeOptionsWire,
    **overrides: Any,
) -> AgentComposeOptionsWire:
    """Return a copy of *base* with *overrides* applied."""

    return replace(base, **overrides)


# pyvision: tests/test_core_agent_compose.py
def build_agent_compose_input(
    *,
    artifact_scan: AgentArtifactScanWire | None = None,
    changespecs: Sequence[ChangeSpecWire] = (),
    running_claims: Sequence[RunningClaimWire] = (),
    alive_pids: Sequence[int] = (),
    dead_pids: Sequence[int] = (),
    dismissed_identities: Sequence[tuple[str, str, str | None]] = (),
    dismissed_suffixes: Sequence[str] = (),
    options: AgentComposeOptionsWire | None = None,
) -> AgentComposeInputWire:
    """Assemble one Rust composer input from already-collected host data."""
    return AgentComposeInputWire(
        artifact_scan=artifact_scan,
        changespecs=list(changespecs),
        running_claims=list(running_claims),
        alive_pids=list(alive_pids),
        dead_pids=list(dead_pids),
        dismissed_identities=list(dismissed_identities),
        dismissed_suffixes=list(dismissed_suffixes),
        options=options or AgentComposeOptionsWire(),
    )


def compose_agent_list(input_wire: AgentComposeInputWire) -> ComposedAgentListWire:
    """Return the Rust-composed list for *input_wire*.

    The binding is required and stale wheels fail through
    :func:`sase.core.rust.require_rust_binding`; no Python fallback is provided.
    The TUI loader uses this route by default; missing or stale Rust bindings fail
    through the strict loader rather than falling back to Python.
    """
    rust_compose = require_rust_binding("compose_agent_list")
    payload = agent_compose_wire_to_json_dict(input_wire)
    raw: dict[str, Any] = rust_compose(payload)
    return composed_agent_list_from_dict(raw)


def _wire_identity_to_agent_identity(
    identity: tuple[str, str, str | None],
) -> tuple[AgentType, str, str | None]:
    return (AgentType(identity[0]), identity[1], identity[2])


def composed_agent_list_to_agents(record: ComposedAgentListWire) -> list[Agent]:
    """Rehydrate Rust-composed visible rows into normal TUI ``Agent`` models."""

    agents = [agent_from_wire(agent_wire) for agent_wire in record.agents]
    by_identity = {agent.identity: agent for agent in agents}

    for agent, agent_wire in zip(agents, record.agents, strict=True):
        agent.followup_agents = [
            by_identity[identity]
            for identity in (
                _wire_identity_to_agent_identity(item)
                for item in agent_wire.followup_identities
            )
            if identity in by_identity
        ]
        agent.retry_chain_siblings = [
            by_identity[identity]
            for identity in (
                _wire_identity_to_agent_identity(item)
                for item in agent_wire.retry_chain_sibling_identities
            )
            if identity in by_identity
        ]

    return agents


# pyvision: tests/test_core_agent_compose.py
def log_compose_mismatch(
    *,
    label: str,
    expected: ComposedAgentListWire,
    actual: ComposedAgentListWire,
) -> bool:
    """Log compose parity diagnostics and return whether the lists matched."""
    if expected == actual:
        return True
    logger.warning(
        "agent compose parity mismatch for %s: expected=%s actual=%s dropped=%s merge_log=%s",
        label,
        agent_compose_wire_to_json_dict(expected),
        agent_compose_wire_to_json_dict(actual),
        agent_compose_wire_to_json_dict(actual.dropped),
        agent_compose_wire_to_json_dict(actual.merge_log),
    )
    return False


__all__ = [
    "build_agent_compose_input",
    "compose_agent_list",
    "compose_agent_list_reference",
    "composed_agent_list_to_agents",
    "compose_python_agents_to_wire",
    "log_compose_mismatch",
    "with_options",
]
