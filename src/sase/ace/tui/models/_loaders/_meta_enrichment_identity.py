"""Identity and general metadata helpers for agent enrichment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.core.agent_identity_facade import imported_source_owner_from_mapping
from sase.plan_chain import (
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_phase_name,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
)

from ....agent_tribes import InvalidTribeError, validate_tribe_name
from ..agent import Agent, LinkedRepoMetadata

if TYPE_CHECKING:
    from sase.core.agent_scan_wire import AgentMetaWire


def apply_imported_source_owner(agent: Agent, raw: object) -> None:
    """Copy an ``imported_source_owner`` mapping onto *agent* when present."""
    owner = imported_source_owner_from_mapping(raw)
    if owner is not None:
        agent.imported_source_owner = owner


def valid_meta_tribe(raw_value: object) -> str | None:
    if not isinstance(raw_value, str):
        return None
    try:
        return validate_tribe_name(raw_value)
    except InvalidTribeError:
        return None


def parse_linked_repos(raw_value: object) -> tuple[LinkedRepoMetadata, ...]:
    if not isinstance(raw_value, list):
        return ()

    parsed: list[LinkedRepoMetadata] = []
    from sase.linked_repos import is_legacy_static_linked_repo_record

    for item in raw_value:
        if not isinstance(item, dict):
            continue
        if is_legacy_static_linked_repo_record(item):
            continue
        raw_name = item.get("name")
        raw_workspace_dir = item.get("workspace_dir")
        if not isinstance(raw_name, str) or not raw_name:
            continue
        if not isinstance(raw_workspace_dir, str) or not raw_workspace_dir:
            continue
        parsed.append(
            LinkedRepoMetadata(
                name=raw_name,
                workspace_dir=raw_workspace_dir,
            )
        )
    return tuple(parsed)


def meta_has_wait_directive(data: dict[str, object]) -> bool:
    return (
        bool(data.get("wait_for"))
        or bool(data.get("wait_for_beads"))
        or data.get("wait_duration") is not None
        or bool(data.get("wait_until"))
        or data.get("wait_runners") is not None
        or data.get("wait_priority") is not None
        or data.get("queue_weight_explicit") is True
    )


def wire_meta_has_wait_directive(meta: AgentMetaWire) -> bool:
    return (
        bool(meta.wait_for)
        or bool(meta.wait_for_beads)
        or meta.wait_duration is not None
        or bool(meta.wait_until)
        or meta.wait_runners is not None
        or meta.wait_priority is not None
        or meta.queue_weight_explicit
    )


def parent_timestamp_from_meta(
    agent: Agent,
    raw_value: object,
    *,
    workflow_child: bool,
) -> str | None:
    if not raw_value:
        return None
    parent_timestamp = str(raw_value)
    if (
        not workflow_child
        and agent.parent_workflow is None
        and agent.raw_suffix is not None
        and parent_timestamp == agent.raw_suffix
    ):
        return None
    return parent_timestamp


def is_main_workflow_agent_step(agent: Agent) -> bool:
    return (
        agent.parent_workflow is not None
        and agent.step_type == "agent"
        and agent.parent_step_index is None
    )


def _root_family_name_from_meta(data: dict[str, object]) -> str | None:
    role_suffix = canonical_plan_chain_suffix(data.get("role_suffix"))
    is_root = (
        data.get("plan_chain_root")
        or data.get("agent_family_role") == "root"
        or role_suffix == PLAN_CHAIN_PLAN_SUFFIX
    )
    if not is_root:
        return None
    family = data.get("agent_family")
    if isinstance(family, str) and family:
        return family
    name = data.get("name")
    if isinstance(name, str) and name:
        return name
    return None


def _root_child_suffix_from_meta(data: dict[str, object]) -> str:
    return (
        canonical_plan_chain_suffix(data.get("role_suffix")) or PLAN_CHAIN_PLAN_SUFFIX
    )


def apply_workflow_child_identity_from_meta(
    agent: Agent,
    data: dict[str, object],
) -> None:
    """Derive concrete family identity for the main agent workflow step."""
    if not is_main_workflow_agent_step(agent):
        return
    family = _root_family_name_from_meta(data)
    if family is None:
        return
    child_suffix = _root_child_suffix_from_meta(data)
    child_name = agent_family_phase_name(family, child_suffix)
    agent.agent_name = child_name
    agent.agent_family = family
    agent.agent_family_role = agent_family_role_for_suffix(child_suffix)
    agent.role_suffix = child_suffix


def _root_family_name_from_meta_wire(meta: AgentMetaWire) -> str | None:
    role_suffix = canonical_plan_chain_suffix(meta.role_suffix)
    is_root = (
        meta.plan_chain_root
        or meta.agent_family_role == "root"
        or role_suffix == PLAN_CHAIN_PLAN_SUFFIX
    )
    if not is_root:
        return None
    if meta.agent_family:
        return meta.agent_family
    if meta.name:
        return meta.name
    return None


def _root_child_suffix_from_meta_wire(meta: AgentMetaWire) -> str:
    return canonical_plan_chain_suffix(meta.role_suffix) or PLAN_CHAIN_PLAN_SUFFIX


def apply_workflow_child_identity_from_meta_wire(
    agent: Agent,
    meta: AgentMetaWire,
) -> None:
    """Wire-aware mirror of :func:`apply_workflow_child_identity_from_meta`."""
    if not is_main_workflow_agent_step(agent):
        return
    family = _root_family_name_from_meta_wire(meta)
    if family is None:
        return
    child_suffix = _root_child_suffix_from_meta_wire(meta)
    child_name = agent_family_phase_name(family, child_suffix)
    agent.agent_name = child_name
    agent.agent_family = family
    agent.agent_family_role = agent_family_role_for_suffix(child_suffix)
    agent.role_suffix = child_suffix
