"""Agent name resolution utility for wait coordination.

Scans artifact directories across all projects to find agents by their
assigned name (via %id directive or manual TUI naming).

This package was split out from a single ``names.py`` module. The submodules
group related concerns; the public API re-exported here is unchanged. Two
functions (``resolve_agent_changespec`` and ``reserve_repeat_name_base``)
are defined here rather than in a submodule because their callees are
patched in tests via ``sase.agent.names.<callee>`` — keeping caller and
callee in the same module namespace lets those patches take effect.
"""

import json
import os

from sase.agent.names._auto import (
    allocate_auto_names,
    get_active_agent_name_map,
    get_active_agent_names,
    get_active_child_names,
    get_live_agent_name_map,
    get_live_agent_name_subset,
    get_next_auto_name,
)
from sase.agent.names._claim import claim_agent_name
from sase.agent.names._common import (
    AgentRefError,
    NamedAgent,
    NameCollisionError,
    add_dismissed_prefix,
    is_dismissed_prefixed,
    is_process_alive,
    strip_dismissed_prefix,
)
from sase.agent.names._indexed import (
    INDEXED_AGENT_NAME_MARKER,
    IndexedAgentNameError,
    IndexedAgentNameNotFoundError,
    InvalidIndexedAgentNameTemplateError,
    allocate_indexed_agent_name,
    indexed_agent_name_base,
    is_concrete_indexed_agent_name_for_template,
    is_indexed_agent_name_template,
    latest_indexed_agent_name,
    require_latest_indexed_agent_name,
    resolve_indexed_agent_name_reference,
    validate_indexed_agent_name_template,
)
from sase.agent.names._lookup import (
    AgentClan,
    AgentClanMember,
    AgentFamily,
    AgentFamilyMember,
    find_named_agent,
    find_agent_clan,
    find_agent_family,
    get_most_recent_agent_name,
    is_agent_family_complete,
    is_agent_clan_complete,
    is_workflow_complete,
    most_recent_completed_family_member,
    most_recent_completed_clan_member,
    resolve_resume_agent_name,
    resolve_wait_dependency,
)
from sase.agent.names._migration import (
    ensure_historical_auto_name_migration,
    run_historical_auto_name_migration,
)
from sase.agent.names._registry import (
    claim_registered_name,
    convert_registered_agent_to_family,
    delete_registered_name,
    get_reserved_agent_name_map,
    get_reserved_agent_names,
    get_reserved_clan_names,
    get_reserved_family_names,
    is_name_reserved,
    load_name_registry,
    lookup_registered_name,
    lowest_name_suggestion,
    rebuild_name_registry,
    release_planned_registered_name,
    release_planned_registered_clan_name,
    reserve_registered_name,
    claim_registered_clan_name,
    reserve_registered_clan_name,
    reserve_registered_template_name,
    reserve_registered_template_names,
)
from sase.agent.names._retry import allocate_retry_name, retry_agent_name_template
from sase.agent.names._resume import (
    active_resume_reserved_names,
    active_wait_reserved_names,
    agent_name_allocation_lock,
    allocate_resume_name,
    allocate_resume_names,
    allocate_wait_name,
    allocate_wait_names,
    first_fork_agent_name,
    first_resume_agent_name,
    fork_agent_names,
    has_fork_reference,
    resume_agent_name_template,
    single_wait_agent_name,
    sole_resume_agent_name,
    wait_agent_name_template,
)
from sase.agent.names._templates import (
    AGENT_NAME_TEMPLATE_MARKER,
    AgentNameTemplate,
    AgentNameTemplateError,
    AgentNameTemplateNotFoundError,
    AgentNameNamespaceReservationIndex,
    InvalidAgentNameTemplateError,
    InvalidAgentNameTemplateTokenError,
    agent_name_template_namespace_template,
    agent_name_template_base,
    allocate_agent_name_template,
    compare_agent_name_template_tokens,
    is_agent_name_template,
    iter_agent_name_template_tokens,
    latest_agent_name_template,
    match_agent_name_template,
    parse_agent_name_template,
    render_agent_name_template_namespace,
    render_agent_name_template,
    require_latest_agent_name_template,
    resolve_agent_name_template_reference,
)
from sase.agent.names._wipe import AgentNameWipeResult, wipe_agent_name_for_reuse


def resolve_agent_changespec(name: str) -> str:
    """Resolve a named agent to its changespec (branch/ChangeSpec name).

    Raises AgentRefError for all failure modes.
    """
    agent = find_named_agent(name)
    if agent is None:
        raise AgentRefError(f"No agent found with name '{name}'")
    if not agent.is_done:
        raise AgentRefError(
            f"Agent '{name}' is still running. "
            f"Use %wait:{name} to wait for it to complete before referencing it with @{name}"
        )
    if agent.outcome != "completed":
        raise AgentRefError(
            f"Agent '{name}' failed (outcome: {agent.outcome}). "
            f"Cannot reference a failed agent's PR with @{name}"
        )

    # Read done.json to get meta_changespec
    done_path = os.path.join(agent.artifacts_dir, "done.json")
    try:
        with open(done_path, encoding="utf-8") as f:
            done_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise AgentRefError(
            f"Cannot read done marker for agent '{name}': {exc}"
        ) from exc

    step_output = done_data.get("step_output")
    if not step_output or not isinstance(step_output, dict):
        raise AgentRefError(
            f"Agent '{name}' has no step output. "
            f"The agent must have run a #pr workflow to create a PR."
        )

    changespec = step_output.get("meta_changespec")
    if not changespec:
        # Legacy fallback
        meta_new_cl = step_output.get("meta_new_cl")
        if meta_new_cl:
            value = str(meta_new_cl).strip()
            paren_idx = value.rfind(" (")
            changespec = value[:paren_idx].strip() if paren_idx > 0 else value
    if not changespec:
        raise AgentRefError(
            f"Agent '{name}' completed but did not create a PR. "
            f"The agent must have run a #pr workflow to use @{name} syntax."
        )

    return str(changespec).strip()


def reserve_repeat_name_base(explicit_base: str | None, count: int) -> str:
    """Return a repeat-batch base name with ``count`` free ``<base>.<k>`` slots.

    When *explicit_base* is provided, verify none of ``<explicit_base>.1``
    through ``<explicit_base>.<count>`` is currently claimed by an active
    agent and raise :class:`NameCollisionError` otherwise.

    When *explicit_base* is ``None``, delegate to :func:`get_next_auto_name`.
    The auto sequence (``0, 1, ..., z, 00, ...``) never collides with an
    existing batch because active agents' ``workflow_name`` reserves the
    base (see :func:`get_active_agent_names`).
    """
    if count <= 0:
        raise ValueError(f"count must be positive, got {count}")
    if explicit_base is None:
        return get_next_auto_name()

    existing = get_active_child_names(explicit_base)
    conflicts = [
        f"{explicit_base}.{k}"
        for k in range(1, count + 1)
        if f"{explicit_base}.{k}" in existing
    ]
    if conflicts:
        raise NameCollisionError(
            f"agent name '{explicit_base}' would collide at "
            f"{', '.join(repr(c) for c in conflicts)} — dismiss or wait for "
            f"the existing agent, or pick a different base name"
        )
    return explicit_base


__all__ = [
    "AgentClan",
    "AgentClanMember",
    "AgentRefError",
    "AgentNameWipeResult",
    "AgentFamily",
    "AgentFamilyMember",
    "AGENT_NAME_TEMPLATE_MARKER",
    "AgentNameTemplate",
    "AgentNameTemplateError",
    "AgentNameTemplateNotFoundError",
    "AgentNameNamespaceReservationIndex",
    "INDEXED_AGENT_NAME_MARKER",
    "IndexedAgentNameError",
    "IndexedAgentNameNotFoundError",
    "InvalidAgentNameTemplateError",
    "InvalidAgentNameTemplateTokenError",
    "InvalidIndexedAgentNameTemplateError",
    "NameCollisionError",
    "NamedAgent",
    "add_dismissed_prefix",
    "active_resume_reserved_names",
    "active_wait_reserved_names",
    "agent_name_template_base",
    "agent_name_template_namespace_template",
    "allocate_agent_name_template",
    "allocate_auto_names",
    "allocate_indexed_agent_name",
    "agent_name_allocation_lock",
    "allocate_retry_name",
    "allocate_resume_name",
    "allocate_resume_names",
    "allocate_wait_name",
    "allocate_wait_names",
    "claim_agent_name",
    "claim_registered_name",
    "convert_registered_agent_to_family",
    "compare_agent_name_template_tokens",
    "delete_registered_name",
    "find_named_agent",
    "find_agent_family",
    "find_agent_clan",
    "first_fork_agent_name",
    "first_resume_agent_name",
    "fork_agent_names",
    "has_fork_reference",
    "get_active_agent_name_map",
    "get_active_agent_names",
    "get_active_child_names",
    "get_live_agent_name_map",
    "get_live_agent_name_subset",
    "get_most_recent_agent_name",
    "get_next_auto_name",
    "get_reserved_agent_name_map",
    "get_reserved_agent_names",
    "get_reserved_clan_names",
    "get_reserved_family_names",
    "ensure_historical_auto_name_migration",
    "indexed_agent_name_base",
    "is_agent_name_template",
    "is_concrete_indexed_agent_name_for_template",
    "is_name_reserved",
    "is_dismissed_prefixed",
    "is_indexed_agent_name_template",
    "is_process_alive",
    "is_agent_family_complete",
    "is_agent_clan_complete",
    "is_workflow_complete",
    "iter_agent_name_template_tokens",
    "latest_agent_name_template",
    "latest_indexed_agent_name",
    "load_name_registry",
    "lookup_registered_name",
    "lowest_name_suggestion",
    "match_agent_name_template",
    "require_latest_indexed_agent_name",
    "parse_agent_name_template",
    "render_agent_name_template_namespace",
    "render_agent_name_template",
    "reserve_repeat_name_base",
    "resume_agent_name_template",
    "resolve_agent_name_template_reference",
    "resolve_indexed_agent_name_reference",
    "require_latest_agent_name_template",
    "rebuild_name_registry",
    "release_planned_registered_name",
    "most_recent_completed_family_member",
    "most_recent_completed_clan_member",
    "reserve_registered_name",
    "claim_registered_clan_name",
    "reserve_registered_clan_name",
    "release_planned_registered_clan_name",
    "reserve_registered_template_name",
    "reserve_registered_template_names",
    "resolve_agent_changespec",
    "resolve_resume_agent_name",
    "resolve_wait_dependency",
    "retry_agent_name_template",
    "run_historical_auto_name_migration",
    "single_wait_agent_name",
    "sole_resume_agent_name",
    "strip_dismissed_prefix",
    "validate_indexed_agent_name_template",
    "wait_agent_name_template",
    "wipe_agent_name_for_reuse",
]
