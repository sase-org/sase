"""Navigation and lookup helpers for notification actions.

Provides agent/patch lookup by notification fields and tab navigation.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from typing import Protocol

from sase.notifications.agent_matching import (
    agent_matches_notification_identity as agent_matches_notification_identity,
)
from sase.project_display_names import humanize_cl_name

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


class _NamedPatch(Protocol):
    name: str


def _find_patch_index_by_name(
    patches: Sequence[_NamedPatch], patch_name: str
) -> int | None:
    """Find a Patch index, preferring exact names over suffix fallback."""
    from sase.core.patch import patch_names_match

    fallback_idx: int | None = None
    for idx, cs in enumerate(patches):
        if cs.name == patch_name:
            return idx
        if fallback_idx is None and patch_names_match(cs.name, patch_name):
            fallback_idx = idx

    return fallback_idx


def _get_app_patches(app: object) -> Sequence[_NamedPatch]:
    patches = getattr(app, "patches", None)
    if patches is not None:
        return patches
    return getattr(app, "changespecs", [])  # legacy compatibility alias


def _get_load_patches(app: object) -> object:
    load_patches = getattr(app, "_load_patches", None)
    if load_patches is not None:
        return load_patches
    return getattr(app, "_load_changespecs", None)  # legacy compatibility alias


def find_agent_for_notification(
    app: object, notification: Notification
) -> Agent | None:
    """Find the agent matching a notification's identity fields.

    Matches notification routing metadata against the currently loaded agents
    list. Timestamped notifications can match by agent_cl_name or agent_name.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            agent identity and optionally agent_timestamp / agent_root_timestamp.

    Returns:
        The matching Agent, or None if not found.
    """
    agents: list[Agent] = app._agents  # type: ignore[attr-defined]
    for agent in agents:
        if agent_matches_notification_identity(agent, notification):
            return agent

    return None


def find_agents_for_notification(
    app: object, notification: Notification
) -> list[Agent]:
    """Find every loaded agent row matching a notification's identity.

    Unlike :func:`find_agent_for_notification`, this returns all matches. A
    single ``UserQuestion`` (or ``PlanApproval``) notification carries both
    ``agent_timestamp`` (the concrete asking child row) and
    ``agent_root_timestamp`` (the root/aggregate row); both rows can be loaded
    at the same time and each holds its own status override keyed by
    ``Agent.identity`` (which includes ``raw_suffix``). Status mutations must
    visit every matched row so the visible root and its asking child stay in
    sync.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            agent identity and optionally agent_timestamp / agent_root_timestamp.

    Returns:
        The list of matching agents, in their loaded order (possibly empty).
    """
    agents: list[Agent] = app._agents  # type: ignore[attr-defined]
    return [
        agent
        for agent in agents
        if agent_matches_notification_identity(agent, notification)
    ]


def get_meta_patch_name(agent: Agent) -> str | None:
    """Extract Patch name from step output meta variables.

    Checks the new ``meta_patch`` variable first (from v2 xprompts),
    then falls back to legacy ``meta_new_cl`` / ``meta_new_pr`` formats
    for agents that ran with older xprompts.

    Args:
        agent: The agent to check.

    Returns:
        The Patch name if found, or None.
    """
    step_output = agent.step_output
    if not step_output or not isinstance(step_output, dict):
        return None

    # New canonical path: meta_patch contains the Patch name directly
    meta_patch = step_output.get("meta_patch")
    if meta_patch:
        return str(meta_patch).strip()

    meta_changespec = step_output.get("meta_changespec")  # legacy compatibility alias
    if meta_changespec:  # legacy compatibility alias
        return str(meta_changespec).strip()  # legacy compatibility alias

    # Legacy project-agent metadata name.
    meta_patch = step_output.get("meta_patch")
    if meta_patch:
        return str(meta_patch).strip()

    # Legacy support: meta_new_cl format is "full_cl_name (url)"
    meta_new_cl = step_output.get("meta_new_cl")
    if meta_new_cl:
        value = str(meta_new_cl).strip()
        paren_idx = value.rfind(" (")
        if paren_idx > 0:
            return value[:paren_idx].strip()
        return value

    # Legacy support: meta_new_pr + meta_patch
    meta_new_pr = step_output.get("meta_new_pr")
    if meta_new_pr:
        meta_cs = step_output.get(
            "meta_patch"
        ) or step_output.get(  # legacy compatibility alias
            "meta_changespec"  # legacy compatibility alias
        )
        if meta_cs:
            return str(meta_cs).strip()

    return None


get_meta_changespec_name = get_meta_patch_name  # legacy compatibility alias


def navigate_to_agent_tab(app: object, cl_name: str, pid: int | None = None) -> bool:
    """Navigate to an agent in the Agents tab.

    Matches by PID first (most precise), then falls back to cl_name.

    Args:
        app: The AceApp instance.
        cl_name: The Patch name to match.
        pid: Optional PID for precise matching.

    Returns:
        True if the agent was found and selected.
    """
    app.current_tab = "agents"  # type: ignore[attr-defined]

    agents: list[Agent] = app._agents  # type: ignore[attr-defined]

    # Try PID match first (most precise)
    if pid is not None:
        for idx, agent in enumerate(agents):
            if agent.pid == pid:
                app.current_idx = idx  # type: ignore[attr-defined]
                return True

    # Fallback to cl_name match
    for idx, agent in enumerate(agents):
        if agent.cl_name == cl_name:
            app.current_idx = idx  # type: ignore[attr-defined]
            return True

    app.notify(f"Agent '{humanize_cl_name(cl_name)}' not found", severity="warning")  # type: ignore[attr-defined]
    return False


def navigate_to_patch_tab(app: object, patch_name: str, project_file: str) -> bool:
    """Navigate to a Patch in the Patches tab, changing query if needed.

    1. Switch to Patches tab
    2. Search for patch_name in current filtered list
    3. If found, select it
    4. If NOT found, change query to ``project:<project>``, reload, and select it

    Args:
        app: The AceApp instance.
        patch_name: The name of the Patch to navigate to.
        project_file: Path to the project spec file (used to derive project name).

    Returns:
        True if the patch was found and selected.
    """
    from pathlib import Path

    from ....query import parse_query, to_canonical_string
    from ....query_history import push_to_prev_stack, save_query_history
    from ...artifact_tabs import switch_to_artifacts_subtab

    switch_to_artifacts_subtab(app, "prs")
    app.current_tab = "patches"  # type: ignore[attr-defined]

    # Search in current filtered list
    patches = _get_app_patches(app)
    idx = _find_patch_index_by_name(patches, patch_name)
    if idx is not None:
        app.current_idx = idx  # type: ignore[attr-defined]
        return True

    # Not found — change query to show the target Patch
    if not project_file:
        app.notify(  # type: ignore[attr-defined]
            f"Patch '{patch_name}' not found", severity="warning"
        )
        return False

    project_name = Path(project_file).parent.name
    new_query = f"project:{project_name}"

    try:
        new_parsed = parse_query(new_query)
        new_canonical = to_canonical_string(new_parsed)
        current_canonical = app.canonical_query_string  # type: ignore[attr-defined]

        # Push old query to history so user can go back with ^
        if new_canonical != current_canonical:
            push_to_prev_stack(
                current_canonical,
                app._query_history,  # type: ignore[attr-defined]
            )
            save_query_history(app._query_history)  # type: ignore[attr-defined]

        app.parsed_query = new_parsed  # type: ignore[attr-defined]
        app.query_string = new_query  # type: ignore[attr-defined]
        load_patches = _get_load_patches(app)
        if callable(load_patches):
            load_patches()
        app._save_current_query()  # type: ignore[attr-defined]

        # Search again in the new list
        patches = _get_app_patches(app)
        idx = _find_patch_index_by_name(patches, patch_name)
        if idx is not None:
            app.current_idx = idx  # type: ignore[attr-defined]
            return True

    except Exception as e:
        app.notify(  # type: ignore[attr-defined]
            f"Navigation error: {e}", severity="error"
        )
        return False

    app.notify(  # type: ignore[attr-defined]
        f"Patch '{patch_name}' not found", severity="warning"
    )
    return False


def navigate_to_changespec_tab(  # legacy compatibility alias
    app: object,
    patch_name: str,
    project_file: str,
) -> bool:
    """Legacy wrapper preserving the old ChangeSpecs tab id on success."""
    result = navigate_to_patch_tab(app, patch_name, project_file)
    if result:
        app.current_tab = "changespecs"  # type: ignore[attr-defined]  # legacy compatibility alias
    return result
