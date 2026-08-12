"""Diff badge helpers for TUI agent status override passes."""

from ._diff_badge import diff_has_real_edits
from .agent import Agent

DiffBadgeResultCache = dict[str, bool]


def diff_has_real_edits_cached(
    diff_path: str, result_cache: DiffBadgeResultCache | None
) -> bool:
    """Classify *diff_path*, deduped by path when a shared cache is supplied.

    ``diff_has_real_edits`` already caches its result keyed by
    ``(path, mtime_ns, size)``, but a cache hit still pays an ``os.stat``. A
    caller classifying many candidates that share referenced paths -- the
    same diff propagated onto a parent/child row, or several rows citing the
    same linked-repo commit -- should pass a *result_cache* so each unique
    path is stat'd/read at most once per pass, not once per reference. Public
    because :mod:`sase.ace.tui.actions.agents._loading_diff_badges` reuses it
    for the deferred background classification pass.
    """
    if result_cache is None:
        return diff_has_real_edits(diff_path)
    cached = result_cache.get(diff_path)
    if cached is None:
        cached = diff_has_real_edits(diff_path)
        result_cache[diff_path] = cached
    return cached


def classify_linked_commit_diffs(
    agent: Agent, *, result_cache: DiffBadgeResultCache | None = None
) -> bool | None:
    """Classify persisted non-primary commit diffs for the row badge.

    Public because :mod:`sase.ace.tui.actions.agents._loading_diff_badges`
    reuses it for the deferred background classification pass.
    """
    from sase.ace.tui.widgets.prompt_panel._agent_commits import agent_commit_diffs

    linked_diffs = [
        commit_diff
        for commit_diff in agent_commit_diffs(agent)
        if not commit_diff.is_primary
    ]
    if not linked_diffs:
        return None
    return any(
        diff_has_real_edits_cached(commit_diff.diff_path, result_cache)
        for commit_diff in linked_diffs
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


def classify_diff_badges(
    agents: list[Agent], *, result_cache: DiffBadgeResultCache | None = None
) -> None:
    """Classify cheap persisted diff badges for every agent.

    Only reads the finalized ``diff_path`` artifact, which is fast and never
    touches a workspace or VCS provider. The live workspace pencil hint for
    active rows without a ``diff_path`` is intentionally left untouched here:
    computing it inline ran hundreds of live VCS diffs on the first agents
    load and dominated startup. That work is deferred to a background pass
    (:func:`classify_live_file_change_hint`); ``live_file_change_hint`` keeps
    whatever a prior deferred pass computed (``None`` for freshly loaded
    rows).

    This classifier itself is no longer called from the startup-critical
    loader pass either (see ``AgentDiffBadgeMixin``); pass a *result_cache*
    when classifying a batch of candidate rows so paths referenced by more
    than one row -- or more than once on the same row -- are read at most
    once.
    """
    for agent in agents:
        agent.diff_has_real_edits = (
            diff_has_real_edits_cached(agent.diff_path, result_cache)
            if agent.diff_path
            else None
        )
        agent.linked_file_change_hint = classify_linked_commit_diffs(
            agent, result_cache=result_cache
        )
