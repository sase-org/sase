"""Diff badge helpers for TUI agent status override passes."""

from ._diff_badge import diff_has_real_edits
from .agent import Agent


def _classify_linked_commit_diffs(agent: Agent) -> bool | None:
    """Classify persisted non-primary commit diffs for the row badge."""
    from sase.ace.tui.widgets.prompt_panel._agent_commits import agent_commit_diffs

    linked_diffs = [
        commit_diff
        for commit_diff in agent_commit_diffs(agent)
        if not commit_diff.is_primary
    ]
    if not linked_diffs:
        return None
    return any(
        diff_has_real_edits(commit_diff.diff_path) for commit_diff in linked_diffs
    )


def classify_live_file_change_hint(agent: Agent) -> bool | None:
    """Compute the active-workspace-first pencil hint for a row.

    This is the *expensive* classification path: it runs a live VCS diff
    (``get_vcs_provider`` + ``diff_with_untracked``) for the agent's
    workspace. It must NOT run on the startup-critical loader pass -- the
    Agents TUI schedules it as deferred, coalesced background work after the
    first load applies (see ``AgentLiveHintMixin``).

    A persisted primary diff is only a fallback while the resolved source is
    active: a dirty workspace must win, while a clean, unresolvable, or failed
    probe may reuse that persisted classification. Terminal sources never
    reach this helper. Redirected root Plan/Tale rows resolve to their active
    coder child inside ``live_agent_file_change_hint``.

    Fails closed (returns ``None``) on any error so live VCS access can never
    destabilize row rendering.
    """
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
        agent.linked_file_change_hint = _classify_linked_commit_diffs(agent)
