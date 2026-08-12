"""Deferred, coalesced persisted diff-badge classification for the Agents tab.

Row rendering can only show the file-change pencil badge from its
precomputed ``diff_has_real_edits`` / ``linked_file_change_hint`` fields (see
``agent_file_change_hint`` in ``_agent_list_render_cache.py``). Classifying
those fields reads every referenced persisted diff -- the row's own
``diff_path`` plus any non-primary linked-repo commit diffs -- which measured
~0.40 s over 213 rows on the startup-critical loader pass. This mixin moves
that work off the loader: after an Agents load has applied, a coalesced
background worker classifies the small set of visible rows that still need
it, runs the disk reads off the event loop deduped by referenced path, and
patches the affected rows in place by identity.

First paint and j/k navigation are never gated on this classification. With
it deferred, ``agent_file_change_hint`` falls through to
``bool(agent.diff_path)`` for any row whose badge is still ``None`` -- so on
the *first* paint of a session:

- a row whose persisted diff touches only plan/prompt bookkeeping briefly
  shows a pencil and then loses it once the deferred pass classifies it
  ``False``;
- a row whose only real change is a linked-repo commit diff briefly shows no
  pencil and then gains one once the deferred pass classifies it ``True``.

Both settle within one deferred pass, and ``carry_over_diff_badges`` means
this only happens once per session rather than on every reload -- the same
stale-while-revalidate contract ``_loading_live_hints.py`` already ships for
the live workspace hint.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ...models._agent_status_diff import (
    classify_linked_commit_diffs,
    diff_has_real_edits_cached,
    DiffBadgeResultCache,
)
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

log = logging.getLogger(__name__)

DiffBadgeResult = tuple[bool | None, bool | None]


def _linked_diff_paths(agent: Agent) -> tuple[str, ...]:
    """Return the agent's referenced non-primary commit diff paths.

    A cheap in-memory parse of ``step_output`` (see ``agent_commit_diffs``),
    used both to scope candidates and to compare identity across a reload in
    :func:`carry_over_diff_badges`.
    """
    from sase.ace.tui.widgets.prompt_panel._agent_commits import agent_commit_diffs

    return tuple(
        commit_diff.diff_path
        for commit_diff in agent_commit_diffs(agent)
        if not commit_diff.is_primary
    )


def _agent_needs_diff_badge_pass(agent: Agent) -> bool:
    """Whether *agent* has an unclassified badge field it references."""
    if agent.diff_path is not None and agent.diff_has_real_edits is None:
        return True
    return agent.linked_file_change_hint is None and bool(_linked_diff_paths(agent))


def carry_over_diff_badges(
    previous_agents: list[Agent],
    current_agents: list[Agent],
) -> None:
    """Carry stale-while-revalidate diff badges onto freshly loaded rows.

    Agents reloads rebuild ``Agent`` objects from disk, so a freshly loaded
    row always starts with both badge fields ``None``. Without carry-over
    every auto-refresh would drop the badge back to the ``bool(diff_path)``
    fallback and the pencil column would flicker on each reload. Carry-over
    only applies when the *referenced diff itself* is unchanged -- the same
    ``diff_path`` for the primary badge, the same ordered set of linked
    commit-diff paths for the linked badge -- so a row whose diff actually
    advanced between loads stays ``None`` and the scheduled background scan
    classifies it fresh rather than reusing a stale answer for a different
    file.
    """
    previous_by_identity: dict[tuple[AgentType, str, str | None], Agent] = {}
    for agent in previous_agents:
        if agent.diff_has_real_edits is None and agent.linked_file_change_hint is None:
            continue
        previous_by_identity[agent.identity] = agent

    if not previous_by_identity:
        return

    for agent in current_agents:
        previous = previous_by_identity.get(agent.identity)
        if previous is None:
            continue
        if (
            agent.diff_has_real_edits is None
            and previous.diff_has_real_edits is not None
            and agent.diff_path
            and agent.diff_path == previous.diff_path
        ):
            agent.diff_has_real_edits = previous.diff_has_real_edits
        if (
            agent.linked_file_change_hint is None
            and previous.linked_file_change_hint is not None
            and _linked_diff_paths(agent) == _linked_diff_paths(previous)
        ):
            agent.linked_file_change_hint = previous.linked_file_change_hint


def _compute_diff_badges(
    candidates: list[Agent],
) -> dict[tuple[AgentType, str, str | None], DiffBadgeResult]:
    """Classify diff badges for *candidates* off the event loop.

    Returns a mapping keyed by agent identity rather than mutating the
    candidate ``Agent`` objects in place -- they are the same objects the UI
    thread may be rendering concurrently. A single *result_cache* is shared
    across the whole batch so a path referenced by more than one candidate
    (a badge propagated from a coder child onto its parent row) or more than
    once on the same row (several linked commits sharing a diff) is stat'd
    and read at most once, not once per reference.
    """
    result_cache: DiffBadgeResultCache = {}
    results: dict[tuple[AgentType, str, str | None], DiffBadgeResult] = {}
    for agent in candidates:
        primary = (
            diff_has_real_edits_cached(agent.diff_path, result_cache)
            if agent.diff_path
            else None
        )
        linked = classify_linked_commit_diffs(agent, result_cache=result_cache)
        results[agent.identity] = (primary, linked)
    return results


class AgentDiffBadgeMixin(AgentLoadingStateMixin):
    """Schedule and apply deferred persisted diff-badge classification."""

    # Coalescing state (initialized by ``_init_app_state``):
    #   ``_diff_badge_scan_scheduled`` — a pump-free loop task is queued.
    #   ``_diff_badge_scan_running``  — a worker is mid-flight (off-thread).
    #   ``_diff_badge_scan_pending``  — a request arrived while one ran, so
    #                                   the in-flight worker re-arms itself.
    #   ``_diff_badge_scan_source``   — telemetry tag for the queued scan.
    _diff_badge_scan_scheduled: bool
    _diff_badge_scan_running: bool
    _diff_badge_scan_pending: bool
    _diff_badge_scan_source: str
    _diff_badge_async_tasks: set[asyncio.Task[None]]

    def _schedule_diff_badge_classification(self, *, source: str = "unknown") -> None:
        """Queue a coalesced diff-badge scan once a load has applied.

        No-op before the first agents load (the loader path owns first
        paint) and while a scan is already queued. If a scan is mid-flight,
        mark a trailing request so a burst of refreshes collapses to a
        single follow-up scan rather than overlapping diff reads.
        """
        if not self._agents_first_load_done:
            return
        if self._diff_badge_scan_running:
            self._diff_badge_scan_pending = True
            return
        if self._diff_badge_scan_scheduled:
            return
        self._diff_badge_scan_scheduled = True
        self._diff_badge_scan_source = source
        self._spawn_diff_badge_classification_task()

    def _spawn_diff_badge_classification_task(self) -> None:
        """Run the scan outside Textual's serial app message pump."""
        task = spawn_pump_free_task(
            self,
            self._run_diff_badge_classification(),
            name="sase-agents-diff-badges",
            registry_attr="_diff_badge_async_tasks",
        )
        if task is None:
            self._diff_badge_scan_scheduled = False

    async def _run_diff_badge_classification(self) -> None:
        """Classify badges off-thread, then patch affected rows by identity.

        Defers behind the navigation gate so the post-await apply leg never
        lands mid j/k burst. The diff reads run in a worker thread; results
        are keyed by agent identity so they re-attach correctly even if an
        interleaved refresh rebuilt the agent list while the worker ran.
        """
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(  # type: ignore[attr-defined]
                delay,
                self._spawn_diff_badge_classification_task,
            )
            return
        self._diff_badge_scan_scheduled = False
        candidates = self._diff_badge_candidates()
        if not candidates:
            return
        self._diff_badge_scan_running = True
        try:
            with tui_trace(
                "agents.diff_badge_classification",
                candidates=len(candidates),
                source=self._diff_badge_scan_source,
            ):
                results = await asyncio.to_thread(_compute_diff_badges, candidates)
            self._apply_diff_badge_results(results)
        except Exception:
            log.exception("Diff badge classification failed")
        finally:
            self._diff_badge_scan_running = False
            if self._diff_badge_scan_pending:
                self._diff_badge_scan_pending = False
                self._schedule_diff_badge_classification(source="diff_badge_followup")

    def _diff_badge_candidates(self) -> list[Agent]:
        """Snapshot visible rows with an unclassified badge field.

        Bounded to the currently visible agents (``self._agents``). A row
        whose fields were already carried over from a prior classification
        (see :func:`carry_over_diff_badges`) is skipped, so a burst of
        reloads does not repeatedly re-read the same persisted diffs.
        """
        candidates: list[Agent] = []
        for agent in self._agents:
            if _agent_needs_diff_badge_pass(agent):
                candidates.append(agent)
        return candidates

    def _apply_diff_badge_results(
        self,
        results: dict[tuple[AgentType, str, str | None], DiffBadgeResult],
    ) -> None:
        """Patch rows whose classified badge fields changed on the UI thread.

        Matches results back to the *current* agent objects by identity (the
        list may have been rebuilt since the worker snapshot).
        """
        if not results:
            return
        current_by_identity: dict[tuple[AgentType, str, str | None], Agent] = {}
        for agent in self._agents_with_children:
            current_by_identity.setdefault(agent.identity, agent)
        for agent in self._agents:
            current_by_identity[agent.identity] = agent

        for identity, (primary, linked) in results.items():
            target = current_by_identity.get(identity)
            if target is None:
                continue
            changed = False
            if target.diff_has_real_edits != primary:
                target.diff_has_real_edits = primary
                changed = True
            if target.linked_file_change_hint != linked:
                target.linked_file_change_hint = linked
                changed = True
            if changed:
                self._try_patch_agent_row(target)  # type: ignore[attr-defined]
