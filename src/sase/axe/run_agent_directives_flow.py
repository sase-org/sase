"""Wait and model resolution stages for the run agent runner.

Computes the normalized dependency-wait targets (including implicit
``#fork`` waits) and resolves the launch model/provider selection, reusing
the preserved launch selection on runner re-execs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WaitResolution:
    """Normalized wait targets for dependency and runner-slot waits."""

    wait_names: list[str]
    wait_for_epics_of: list[str]
    wait_identity_deps: list[dict[str, Any]]
    wait_fork_sources: list[dict[str, str]]
    wait_beads: list[str]
    wait_hoods: list[str]
    batch_predecessor_context_payload: dict[str, Any] | None


@dataclass(frozen=True)
class LaunchModelSelection:
    """Resolved launch model, provider, and alias reservation."""

    model: str | None
    llm_provider: str
    reasoning_effort: str | None
    model_alias: str | None
    model_alias_trail: list[str]
    model_alias_origin: str | None
    model_alias_reservation: dict[str, Any] | None


def resolve_wait_state(
    directives: Any,
    *,
    fork_reference_prompt: str,
    batch_predecessor_binding: Any | None,
    agent_session_attach_plan: Any | None,
    wait_targets: Mapping[str, str] | None = None,
    waiter_artifact_dir: str | Path | None = None,
    preserved_metadata: Mapping[str, Any] | None = None,
) -> WaitResolution:
    """Normalize explicit waits plus implicit ``#fork`` parent waits.

    ``wait_targets`` is the ``{name: session|turn}`` hook for explicit
    waits. Binding happens once: runner re-execs reuse persisted
    ``wait_for_artifacts`` / ``wait_for_fork_sources`` and never re-pin a
    current turn.
    """
    from sase.agent.names import fork_agent_names

    wait_names = list(directives.wait)
    preserved_identity = _preserved_record_list(
        preserved_metadata, "wait_for_artifacts"
    )
    preserved_forks = _preserved_record_list(
        preserved_metadata, "wait_for_fork_sources"
    )
    wait_identity_deps: list[dict[str, Any]] = (
        list(preserved_identity) if preserved_identity is not None else []
    )
    batch_predecessor_context_payload: dict[str, Any] | None = None
    if batch_predecessor_binding is not None and (
        batch_predecessor_binding.bound_wait_count
    ):
        wait_names.extend(batch_predecessor_binding.wait_names)
        if preserved_identity is None:
            wait_identity_deps.extend(
                dict(item) for item in batch_predecessor_binding.wait_for_artifacts
            )
        if batch_predecessor_binding.wait_for_artifacts:
            batch_predecessor_context_payload = dict(
                batch_predecessor_binding.wait_for_artifacts[0]
            )
    wait_fork_sources: list[dict[str, str]] = []
    wait_beads = list(directives.wait_beads)
    wait_hoods = list(directives.wait_hoods)
    from sase.core.agent_tribe import (
        is_reserved_tribe_name,
        parse_tribe_reference,
        reserved_tribe_target_reason,
    )

    implicit_fork_wait_targets: list[str] = []
    for fork_wait_target in fork_agent_names(fork_reference_prompt):
        fork_tribe = parse_tribe_reference(fork_wait_target)
        if fork_tribe is not None and is_reserved_tribe_name(fork_tribe):
            raise RuntimeError(
                f"Invalid '#fork' tribe reference {fork_wait_target!r}: "
                f"{reserved_tribe_target_reason(fork_tribe)}"
            )
        if fork_wait_target in wait_names:
            continue
        wait_names.append(fork_wait_target)
        if fork_tribe is None:
            implicit_fork_wait_targets.append(fork_wait_target)
    if agent_session_attach_plan and agent_session_attach_plan.parent_is_running:
        if agent_session_attach_plan.parent_name not in wait_names:
            wait_names.append(agent_session_attach_plan.parent_name)
        if preserved_identity is None:
            wait_identity_deps.append(
                {
                    "project_name": agent_session_attach_plan.parent_project_name,
                    "timestamp": agent_session_attach_plan.parent_timestamp,
                    "artifact_dir": agent_session_attach_plan.parent_artifacts_dir,
                    "name": agent_session_attach_plan.parent_name,
                }
            )

    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        normalize_owned_agent_name,
    )

    machine_identity = AgentIdentitySnapshot.current()

    def normalized_wait_name(name: str) -> str:
        if parse_tribe_reference(name) is not None:
            return name
        return normalize_owned_agent_name(name, machine_identity)

    explicit_wait_names = {normalized_wait_name(name) for name in directives.wait}
    wait_names = list(dict.fromkeys(normalized_wait_name(name) for name in wait_names))
    # Implicit targets added by fork sources, batch predecessors, and the
    # session parent are never armed for epic-follow.
    raw_epics_of = list(getattr(directives, "wait_for_epics_of", []))
    wait_for_epics_of = list(
        dict.fromkeys(normalized_wait_name(name) for name in raw_epics_of)
    )
    wait_for_epics_of = [name for name in wait_for_epics_of if name in set(wait_names)]
    assert set(wait_for_epics_of) <= set(wait_names)
    if preserved_forks is not None:
        wait_fork_sources = [
            {str(key): str(value) for key, value in item.items()}
            for item in preserved_forks
        ]
    elif implicit_fork_wait_targets:
        from sase.agent.fork_waits import fork_wait_dependency

        wait_fork_sources = [
            fork_wait_dependency(normalized_wait_name(name))
            for name in implicit_fork_wait_targets
            if normalized_wait_name(name) not in explicit_wait_names
        ]
    if preserved_identity is None:
        targets = wait_targets
        if targets is None:
            raw_targets = getattr(directives, "wait_targets", None)
            targets = dict(raw_targets) if isinstance(raw_targets, Mapping) else None
        if targets:
            from sase.agent.wait_target_binding import bind_explicit_wait_targets

            normalized_targets = {
                normalized_wait_name(str(name)): str(target)
                for name, target in targets.items()
            }
            wait_identity_deps.extend(
                bind_explicit_wait_targets(
                    normalized_targets,
                    waiter_artifact_dir=waiter_artifact_dir,
                )
            )
    return WaitResolution(
        wait_names=wait_names,
        wait_for_epics_of=wait_for_epics_of,
        wait_identity_deps=wait_identity_deps,
        wait_fork_sources=wait_fork_sources,
        wait_beads=wait_beads,
        wait_hoods=wait_hoods,
        batch_predecessor_context_payload=batch_predecessor_context_payload,
    )


def _preserved_record_list(
    preserved: Mapping[str, Any] | None,
    key: str,
) -> list[dict[str, Any]] | None:
    """Return a copied list of mapping records, or ``None`` when absent."""
    if preserved is None:
        return None
    value = preserved.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        return None
    return [dict(item) for item in value]


def resolve_launch_model_selection(
    directives: Any,
    *,
    preserved_metadata: dict[str, Any],
    model_alias_overrides: dict[str, str],
) -> LaunchModelSelection:
    """Resolve the launch model without re-advancing a load-balanced pool."""
    preserved_model = preserved_metadata.get("model")
    preserved_provider = preserved_metadata.get("llm_provider")
    agent_model: str | None
    agent_llm_provider: str
    agent_reasoning_effort: str | None
    agent_model_alias: str | None
    agent_model_alias_trail: list[str]
    agent_model_alias_origin: str | None
    agent_model_alias_reservation: dict[str, Any] | None
    if isinstance(preserved_model, str) and isinstance(preserved_provider, str):
        # Runner re-execs/resumptions reuse the authoritative launch selection
        # recorded in metadata and must not advance a load-balanced pool again.
        agent_model = preserved_model
        agent_llm_provider = preserved_provider
        preserved_effort = preserved_metadata.get("reasoning_effort")
        preserved_model_alias = preserved_metadata.get("model_alias")
        preserved_model_alias_trail = preserved_metadata.get("model_alias_trail")
        preserved_model_alias_origin = preserved_metadata.get("model_alias_origin")
        preserved_model_alias_reservation = preserved_metadata.get(
            "model_alias_reservation"
        )
        agent_reasoning_effort = (
            preserved_effort if isinstance(preserved_effort, str) else None
        )
        agent_model_alias = (
            preserved_model_alias if isinstance(preserved_model_alias, str) else None
        )
        agent_model_alias_trail = (
            preserved_model_alias_trail
            if (
                isinstance(preserved_model_alias_trail, list)
                and all(
                    isinstance(item, str) and item
                    for item in preserved_model_alias_trail
                )
            )
            else []
        )
        agent_model_alias_origin = (
            preserved_model_alias_origin
            if isinstance(preserved_model_alias_origin, str)
            else None
        )
        agent_model_alias_reservation = (
            dict(preserved_model_alias_reservation)
            if isinstance(preserved_model_alias_reservation, dict)
            else None
        )
    else:
        # Reserve the launch selection now, before dependency and runner-slot
        # waits. The first prompt step redeems this metadata instead of
        # advancing the same load-balanced pool a second time.
        from sase.llm_provider.config import (
            DEFAULT_MODEL_FIELD,
            launch_model_setting_alias,
        )
        from sase.llm_provider.launch_selection import (
            reservation_from_launch_selection,
            resolve_launch_selection,
        )
        from sase.llm_provider.provider_priority import resolve_provider_routing_context

        routing_context = resolve_provider_routing_context()
        selection = resolve_launch_selection(
            directives,
            model_alias_overrides,
            consume=True,
            routing_context=routing_context,
        )
        assert selection is not None
        agent_model = selection.model
        agent_llm_provider = selection.provider
        agent_reasoning_effort = selection.reasoning_effort
        agent_model_alias_trail = list(selection.alias_trail)
        agent_model_alias_origin = selection.alias_origin
        agent_model_alias = directives.model_alias
        if not directives.model:
            agent_model_alias = launch_model_setting_alias(
                DEFAULT_MODEL_FIELD,
                model_alias_overrides,
                routing_context=routing_context,
            )
        agent_model_alias_reservation = (
            reservation_from_launch_selection(
                selection,
                alias=selection.cursor_alias,
            )
            if selection.cursor_alias
            else None
        )
    return LaunchModelSelection(
        model=agent_model,
        llm_provider=agent_llm_provider,
        reasoning_effort=agent_reasoning_effort,
        model_alias=agent_model_alias,
        model_alias_trail=agent_model_alias_trail,
        model_alias_origin=agent_model_alias_origin,
        model_alias_reservation=agent_model_alias_reservation,
    )


__all__ = [
    "LaunchModelSelection",
    "WaitResolution",
    "resolve_launch_model_selection",
    "resolve_wait_state",
]
