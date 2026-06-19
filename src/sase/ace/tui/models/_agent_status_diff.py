"""Diff badge helpers for TUI agent status override passes."""

from ._diff_badge import diff_has_real_edits
from .agent import Agent


def classify_live_file_change_hint(agent: Agent) -> bool | None:
    """Compute the active-workspace pencil hint for a row without a diff_path.

    This is the *expensive* classification path: it runs a live VCS diff
    (``get_vcs_provider`` + ``diff_with_untracked``) for the agent's
    workspace. It must NOT run on the startup-critical loader pass -- the
    Agents TUI schedules it as deferred, coalesced background work after the
    first load applies (see ``AgentLiveHintMixin``).

    Fails closed (returns ``None``) on any error so live VCS access can never
    destabilize row rendering.
    """
    if agent.diff_path:
        return None
    from sase.ace.tui.widgets.file_panel._diff import live_agent_file_change_hint

    try:
        return live_agent_file_change_hint(agent)
    except Exception:
        return None


def classify_diff_badges(agents: list[Agent]) -> None:
    """Classify cheap persisted diff badges for every agent.

    Only reads the finalized ``diff_path`` artifact, which is fast and never
    touches a workspace or VCS provider. The live workspace pencil hint for
    active rows without a ``diff_path`` is intentionally left untouched here:
    computing it inline ran hundreds of live VCS diffs on the first agents
    load and dominated startup. That work is deferred to a background pass
    (:func:`classify_live_file_change_hint`); ``live_file_change_hint`` keeps
    whatever a prior deferred pass computed (``None`` for freshly loaded
    rows).
    """
    for agent in agents:
        agent.diff_has_real_edits = (
            diff_has_real_edits(agent.diff_path) if agent.diff_path else None
        )
