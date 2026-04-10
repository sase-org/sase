"""Navigation and lookup helpers for notification actions.

Provides agent/changespec lookup by notification fields and tab navigation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


def find_agent_for_notification(
    app: object, notification: Notification
) -> Agent | None:
    """Find the agent matching a notification's identity fields.

    Matches by agent_cl_name + agent_timestamp in action_data against
    the currently loaded agents list.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            agent_cl_name and optionally agent_timestamp.

    Returns:
        The matching Agent, or None if not found.
    """
    cl_name = notification.action_data.get("agent_cl_name")
    if not cl_name:
        return None

    agent_timestamp = notification.action_data.get("agent_timestamp")

    # Normalize timestamp to 14-digit format for comparison with
    # agent.raw_suffix (which is always normalized to 14-digit).
    from ...models._timestamps import normalize_to_14_digit

    agent_timestamp = normalize_to_14_digit(agent_timestamp)

    agents: list[Agent] = app._agents  # type: ignore[attr-defined]
    for agent in agents:
        if agent.cl_name != cl_name:
            continue
        if agent_timestamp and agent.raw_suffix != agent_timestamp:
            continue
        return agent

    return None


def get_meta_changespec_name(agent: Agent) -> str | None:
    """Extract ChangeSpec name from step output meta variables.

    Checks the new ``meta_changespec`` variable first (from v2 xprompts),
    then falls back to legacy ``meta_new_cl`` / ``meta_new_pr`` formats
    for agents that ran with older xprompts.

    Args:
        agent: The agent to check.

    Returns:
        The ChangeSpec name if found, or None.
    """
    step_output = agent.step_output
    if not step_output or not isinstance(step_output, dict):
        return None

    # New canonical path: meta_changespec contains the ChangeSpec name directly
    meta_changespec = step_output.get("meta_changespec")
    if meta_changespec:
        return str(meta_changespec).strip()

    # Legacy support: meta_new_cl format is "full_cl_name (url)"
    meta_new_cl = step_output.get("meta_new_cl")
    if meta_new_cl:
        value = str(meta_new_cl).strip()
        paren_idx = value.rfind(" (")
        if paren_idx > 0:
            return value[:paren_idx].strip()
        return value

    # Legacy support: meta_new_pr + meta_changespec
    meta_new_pr = step_output.get("meta_new_pr")
    if meta_new_pr:
        meta_cs = step_output.get("meta_changespec")
        if meta_cs:
            return str(meta_cs).strip()

    return None


def navigate_to_agent_tab(app: object, cl_name: str, pid: int | None = None) -> bool:
    """Navigate to an agent in the Agents tab.

    Matches by PID first (most precise), then falls back to cl_name.

    Args:
        app: The AceApp instance.
        cl_name: The CL name to match.
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

    app.notify(f"Agent '{cl_name}' not found", severity="warning")  # type: ignore[attr-defined]
    return False


def navigate_to_changespec_tab(
    app: object, changespec_name: str, project_file: str
) -> bool:
    """Navigate to a ChangeSpec in the CLs tab, changing query if needed.

    1. Switch to CLs tab
    2. Search for changespec_name in current filtered list
    3. If found, select it
    4. If NOT found, change query to ``project:<project>``, reload, and select it

    Args:
        app: The AceApp instance.
        changespec_name: The name of the ChangeSpec to navigate to.
        project_file: Path to the .gp project file (used to derive project name).

    Returns:
        True if the changespec was found and selected.
    """
    from pathlib import Path

    from sase.core.changespec import changespec_names_match

    from ....query import parse_query, to_canonical_string
    from ....query_history import push_to_prev_stack, save_query_history

    app.current_tab = "changespecs"  # type: ignore[attr-defined]

    # Search in current filtered list
    changespecs = app.changespecs  # type: ignore[attr-defined]
    for idx, cs in enumerate(changespecs):
        if changespec_names_match(cs.name, changespec_name):
            app.current_idx = idx  # type: ignore[attr-defined]
            return True

    # Not found — change query to show the target ChangeSpec
    if not project_file:
        app.notify(  # type: ignore[attr-defined]
            f"ChangeSpec '{changespec_name}' not found", severity="warning"
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
        app._load_changespecs()  # type: ignore[attr-defined]
        app._save_current_query()  # type: ignore[attr-defined]

        # Search again in the new list
        changespecs = app.changespecs  # type: ignore[attr-defined]
        for idx, cs in enumerate(changespecs):
            if changespec_names_match(cs.name, changespec_name):
                app.current_idx = idx  # type: ignore[attr-defined]
                return True

    except Exception as e:
        app.notify(  # type: ignore[attr-defined]
            f"Navigation error: {e}", severity="error"
        )
        return False

    app.notify(  # type: ignore[attr-defined]
        f"ChangeSpec '{changespec_name}' not found", severity="warning"
    )
    return False
