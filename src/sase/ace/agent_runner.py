"""Headless agent runner for the ace TUI using Textual's pilot API."""

import json
from typing import Any, Literal

from sase.ace.tui import AceApp


async def run_agent_mode(
    query: str = '"(!: "',
    keys: list[str] | None = None,
    size: tuple[int, int] = (120, 40),
    model_tier_override: Literal["large", "small"] | None = None,
) -> str:
    """Run the ace TUI headlessly and return JSON with screen, state, and error.

    Args:
        query: Query string for filtering ChangeSpecs.
        keys: Optional list of key names to press via the pilot.
        size: Terminal size as (width, height).
        model_tier_override: Override model tier for LLM providers.

    Returns:
        JSON string with keys: screen, state, error.
    """
    try:
        app = AceApp(
            query=query,
            model_tier_override=model_tier_override,
            refresh_interval=0,
        )
        async with app.run_test(size=size) as pilot:
            if keys:
                await pilot.press(*keys)
            screen = capture_screen(app, size[1])
            state = extract_state(app)
            return json.dumps({"screen": screen, "state": state, "error": None})
    except Exception as e:
        return json.dumps({"screen": "", "state": {}, "error": str(e)})


def capture_screen(app: AceApp, height: int) -> str:
    """Capture the current screen content as plain text."""
    lines = [app.screen.render_line(y).text for y in range(height)]
    return "\n".join(lines)


def _get_modal_name(app: AceApp) -> str | None:
    """Return the class name of the top modal, or None if no modal is open."""
    if len(app.screen_stack) > 1:
        return type(app.screen_stack[-1]).__name__
    return None


def extract_state(app: AceApp) -> dict[str, Any]:
    """Extract structured state from the app's reactive properties."""
    state: dict[str, Any] = {
        "tab": app.current_tab,
        "idx": app.current_idx,
        "total": len(app.changespecs),
        "query": app.query_string,
        "canonical_query": app.canonical_query_string,
        "marked": sorted(app.marked_indices),
        "modal": _get_modal_name(app),
        "hide_reverted": app.hide_reverted,
        "hooks_collapsed": app.hooks_collapsed.value,
        "commits_collapsed": app.commits_collapsed.value,
        "mentors_collapsed": app.mentors_collapsed.value,
    }

    # Selected changespec info
    if app.changespecs and 0 <= app.current_idx < len(app.changespecs):
        cs = app.changespecs[app.current_idx]
        state["selected"] = {
            "name": cs.name,
            "status": cs.status,
            "cl": cs.cl,
            "parent": cs.parent,
            "project": cs.project_basename,
            "description": cs.description[:200] if cs.description else None,
            "commit_count": len(cs.commits) if cs.commits else 0,
            "hook_count": len(cs.hooks) if cs.hooks else 0,
            "has_comments": bool(cs.comments),
            "has_mentors": bool(cs.mentors),
        }
    else:
        state["selected"] = None

    # Tab-specific state
    if app.current_tab == "agents":
        state["agent_count"] = len(app._agents)
        if app._agents and 0 <= app._agents_last_idx < len(app._agents):
            agent = app._agents[app._agents_last_idx]
            state["selected_agent"] = {
                "type": agent.display_type,
                "cl_name": agent.cl_name,
                "status": agent.status,
            }
        else:
            state["selected_agent"] = None
    elif app.current_tab == "axe":
        state["axe_running"] = app.axe_running

    return state
