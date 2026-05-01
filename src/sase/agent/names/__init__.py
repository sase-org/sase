"""Agent name resolution utility for wait coordination.

Scans artifact directories across all projects to find agents by their
assigned name (via %name directive or manual TUI naming).

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
    allocate_revived_name,
    dedup_name,
    get_active_agent_name_map,
    get_active_agent_names,
    get_active_child_names,
    get_live_agent_name_map,
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
from sase.agent.names._dismissed import (
    allocate_dismissed_name,
    collect_dismissed_taken_names,
)
from sase.agent.names._lookup import (
    find_named_agent,
    get_most_recent_agent_name,
    is_workflow_complete,
)
from sase.agent.names._resume import (
    agent_name_allocation_lock,
    allocate_resume_name,
    allocate_resume_names,
    first_resume_agent_name,
)


def resolve_agent_changespec(name: str) -> str:
    """Resolve a named agent to its changespec (branch/CL name).

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
            f"Agent '{name}' completed but did not create a PR/CL. "
            f"The agent must have run a #pr workflow to use @{name} syntax."
        )

    return str(changespec).strip()


def reserve_repeat_name_base(explicit_base: str | None, count: int) -> str:
    """Return a repeat-batch base name with ``count`` free ``<base>.<k>`` slots.

    When *explicit_base* is provided, verify none of ``<explicit_base>.1``
    through ``<explicit_base>.<count>`` is currently claimed by an active
    agent and raise :class:`NameCollisionError` otherwise.

    When *explicit_base* is ``None``, delegate to :func:`get_next_auto_name`.
    The auto sequence (``a, b, ..., z, aa, ...``) never collides with an
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
    "AgentRefError",
    "NameCollisionError",
    "NamedAgent",
    "add_dismissed_prefix",
    "allocate_auto_names",
    "agent_name_allocation_lock",
    "allocate_dismissed_name",
    "allocate_resume_name",
    "allocate_resume_names",
    "allocate_revived_name",
    "claim_agent_name",
    "collect_dismissed_taken_names",
    "dedup_name",
    "find_named_agent",
    "first_resume_agent_name",
    "get_active_agent_name_map",
    "get_active_agent_names",
    "get_active_child_names",
    "get_live_agent_name_map",
    "get_most_recent_agent_name",
    "get_next_auto_name",
    "is_dismissed_prefixed",
    "is_process_alive",
    "is_workflow_complete",
    "reserve_repeat_name_base",
    "resolve_agent_changespec",
    "strip_dismissed_prefix",
]
