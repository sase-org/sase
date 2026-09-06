"""Resolve resume targets and wait dependencies by agent name."""

from __future__ import annotations

import os
from pathlib import Path

from sase.agent.names._common import NamedAgent
from sase.agent.names._lookup_artifacts import (
    is_success_outcome,
    meta_parent_timestamp,
    read_json_dict,
)
from sase.agent.names._lookup_groups import (
    find_agent_clan,
    find_agent_family,
    is_agent_clan_complete,
    is_agent_family_complete,
    most_recent_completed_clan_member,
    most_recent_completed_family_member,
)
from sase.agent.names._lookup_named import find_named_agent
from sase.agent.names._templates import resolve_agent_name_template_reference
from sase.core.agent_identity_facade import (
    AgentFamilyNameKind,
    parse_agent_family_name,
)
from sase.core.agent_tribe import InvalidTribeError, parse_tribe_reference
from sase.plan_chain import AGENT_FAMILY_FIELD


def _self_parallel_family_root(
    base_name: str,
) -> tuple[bool, NamedAgent | None]:
    """Return this member's generation-pinned root for a base-name reference."""
    artifacts_value = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_value:
        return False, None
    artifacts_dir = Path(artifacts_value)
    meta = read_json_dict(artifacts_dir / "agent_meta.json")
    if meta is None:
        return False, None
    if meta.get("agent_family_parallel") is not True:
        return False, None
    from sase.core.agent_identity_facade import current_owner_agent_name_key

    family_name = meta.get(AGENT_FAMILY_FIELD)
    if not isinstance(family_name, str) or current_owner_agent_name_key(
        family_name
    ) != current_owner_agent_name_key(base_name):
        return False, None
    parent_timestamp = meta_parent_timestamp(meta)
    if parent_timestamp is None:
        return False, None

    family = find_agent_family(base_name)
    if (
        family is not None
        and family.root is not None
        and family.root.timestamp == parent_timestamp
    ):
        root = family.root
        return True, NamedAgent(
            name=root.name,
            artifacts_dir=str(root.artifacts_dir),
            is_done=root.is_done,
            outcome=root.outcome,
        )

    # Exact-name recovery covers a plain pre-existing root that acquired a
    # late parallel member but does not itself carry family metadata.
    exact = find_named_agent(base_name)
    if exact is not None and Path(exact.artifacts_dir).name == parent_timestamp:
        return True, exact
    return True, None


def resolve_resume_agent_name(name: str) -> NamedAgent | None:
    """Resolve a ``#fork`` target to the artifact that should provide chat.

    Direct child references such as ``foo-code`` and legacy ``foo.code`` remain
    exact lookups. A root family reference such as ``foo`` resolves to the most
    recent successful member of the newest family generation, falling back to
    exact-name behavior when no family exists.
    """
    name = resolve_agent_name_template_reference(name)
    clan_member = most_recent_completed_clan_member(name)
    if clan_member is not None:
        return clan_member
    is_self_family, self_root = _self_parallel_family_root(name)
    if is_self_family:
        if (
            self_root is not None
            and self_root.is_done
            and is_success_outcome(self_root.outcome)
        ):
            return self_root
        return None
    if not _is_canonical_agent_family_member_name(name):
        family_member = most_recent_completed_family_member(name)
        if family_member is not None:
            return family_member
    return find_named_agent(name, only_done=True)


def _is_canonical_agent_family_member_name(name: str) -> bool:
    try:
        return parse_agent_family_name(name).kind is AgentFamilyNameKind.MEMBER
    except (RuntimeError, ValueError):
        return False


def resolve_wait_dependency(name: str) -> bool:
    """Return whether a wait dependency has completed successfully.

    Tribe waits require the waiting artifact's launch cutoff and therefore
    resolve only through ``WaitDependencyIndex`` runner callers.
    """
    try:
        if parse_tribe_reference(name) is not None:
            return False
    except InvalidTribeError:
        return False
    clan_complete = is_agent_clan_complete(name)
    if clan_complete is not None:
        return clan_complete
    is_self_family, self_root = _self_parallel_family_root(name)
    if is_self_family:
        return bool(
            self_root is not None
            and self_root.is_done
            and is_success_outcome(self_root.outcome)
        )
    complete = is_agent_family_complete(name)
    if complete is not None:
        return complete

    agent = find_named_agent(name, only_done=True)
    return agent is not None and is_success_outcome(agent.outcome)
