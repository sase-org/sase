"""UI-thread apply helpers for loaded agent snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...models._dedup import dedup_by_pid, dedup_running_vs_workflow
from ...models.agent import AgentType
from ._loading_compute import PreparedApplyData
from ._loading_helpers import is_always_visible
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_loader import AgentLoadState


def _reattach_children_after_parent_dedup(
    agents_before_dedup: list[Agent],
    agents_after_dedup: list[Agent],
) -> list[Agent]:
    """Move children from removed same-PID parents to surviving parents."""
    after_ids = {id(agent) for agent in agents_after_dedup}
    surviving_parent_by_pid: dict[int, Agent] = {}
    for agent in agents_after_dedup:
        if agent.pid is None or agent.raw_suffix is None or agent.is_workflow_child:
            continue
        surviving_parent_by_pid.setdefault(agent.pid, agent)

    replacement_suffix_by_removed_suffix: dict[str, str] = {}
    for agent in agents_before_dedup:
        if (
            id(agent) in after_ids
            or agent.pid is None
            or agent.raw_suffix is None
            or agent.is_workflow_child
        ):
            continue
        survivor = surviving_parent_by_pid.get(agent.pid)
        if (
            survivor is None
            or survivor.raw_suffix is None
            or survivor.raw_suffix == agent.raw_suffix
        ):
            continue
        replacement_suffix_by_removed_suffix[agent.raw_suffix] = survivor.raw_suffix

    if not replacement_suffix_by_removed_suffix:
        return agents_after_dedup

    reattached_ids: set[int] = set()
    for agent in agents_after_dedup:
        if not agent.is_workflow_child or agent.parent_timestamp is None:
            continue
        replacement_suffix = replacement_suffix_by_removed_suffix.get(
            agent.parent_timestamp
        )
        if replacement_suffix is None:
            continue
        agent.parent_timestamp = replacement_suffix
        reattached_ids.add(id(agent))

    if not reattached_ids:
        return agents_after_dedup

    children_by_parent: dict[str, list[Agent]] = {}
    roots_and_unchanged_children: list[Agent] = []
    for agent in agents_after_dedup:
        if id(agent) in reattached_ids and agent.parent_timestamp is not None:
            children_by_parent.setdefault(agent.parent_timestamp, []).append(agent)
        else:
            roots_and_unchanged_children.append(agent)

    regrouped: list[Agent] = []
    for agent in roots_and_unchanged_children:
        regrouped.append(agent)
        if agent.raw_suffix is None:
            continue
        regrouped.extend(children_by_parent.pop(agent.raw_suffix, []))

    for remaining_children in children_by_parent.values():
        regrouped.extend(remaining_children)
    return regrouped


class AgentLoadingApplyMixin(AgentLoadingStateMixin):
    """Methods that merge prepared agent data back into app state."""

    def _preserve_revived_agents_for_incomplete_load(
        self,
        prep: PreparedApplyData,
        load_state: AgentLoadState | None,
    ) -> None:
        """Keep revived historical agents visible until Tier 2 reconciles."""
        revived_suffixes = getattr(self, "_revived_agent_raw_suffixes", None)
        if not revived_suffixes:
            return

        loaded_suffixes = {
            agent.raw_suffix
            for agent in prep.filtered_agents
            if agent.raw_suffix is not None
        }
        if load_state is not None and load_state.complete_history:
            revived_suffixes.difference_update(loaded_suffixes)
            return
        if load_state is None or load_state.complete_history:
            return

        missing_suffixes = revived_suffixes - loaded_suffixes
        if not missing_suffixes:
            return

        dismissed_suffixes = {
            raw_suffix
            for _, _, raw_suffix in self._dismissed_agents
            if raw_suffix is not None
        }
        missing_suffixes -= dismissed_suffixes
        if not missing_suffixes:
            return

        existing_identities = {agent.identity for agent in prep.filtered_agents}
        preserved: list[Agent] = []
        preserved_suffixes: set[str] = set()
        for agent in self._agents_with_children:
            if agent.raw_suffix not in missing_suffixes:
                continue
            if agent.identity in existing_identities:
                continue
            if agent.identity in self._dismissed_agents:
                continue
            preserved.append(agent)
            existing_identities.add(agent.identity)
            if agent.raw_suffix is not None:
                preserved_suffixes.add(agent.raw_suffix)

        # Fall back to the dismissed-bundle cache for revived suffixes that
        # never landed in ``_agents_with_children`` (e.g. long-dismissed
        # bundles revived from the archive). The revive flow hydrates those
        # bundle agents into ``_dismissed_agent_objects`` before calling the
        # loader, so the data is on hand for first-paint visibility.
        remaining_suffixes = missing_suffixes - preserved_suffixes
        if remaining_suffixes:
            for agent in self._dismissed_agent_objects:
                if agent.raw_suffix not in remaining_suffixes:
                    continue
                if agent.identity in existing_identities:
                    continue
                if agent.identity in self._dismissed_agents:
                    continue
                preserved.append(agent)
                existing_identities.add(agent.identity)

        if not preserved:
            return

        prep.filtered_agents = [*prep.filtered_agents, *preserved]
        prep.has_always_visible = any(
            is_always_visible(a) for a in prep.filtered_agents
        )
        prep.hideable_agents = [
            agent for agent in prep.filtered_agents if not is_always_visible(agent)
        ]

    def _merge_incomplete_load_after_complete_history(
        self,
        prep: PreparedApplyData,
        load_state: AgentLoadState | None,
    ) -> None:
        """Treat post-reconcile Tier 1 loads as patches over full history."""
        previous_state = getattr(self, "_agent_load_state", None)
        if (
            previous_state is None
            or not previous_state.complete_history
            or load_state is None
            or load_state.complete_history
        ):
            return

        cached_agents = list(getattr(self, "_agents_with_children", []))
        if not cached_agents:
            return

        incoming_by_identity = {agent.identity: agent for agent in prep.filtered_agents}
        dismissed = set(getattr(self, "_dismissed_agents", set()))
        dismissed_suffixes = {
            raw_suffix for _, _, raw_suffix in dismissed if raw_suffix is not None
        }
        dismissed_cl_suffixes = {
            (cl_name, raw_suffix)
            for _, cl_name, raw_suffix in dismissed
            if raw_suffix is not None
        }

        def is_dismissed(agent: Agent) -> bool:
            if agent.identity in dismissed:
                return True
            if agent.raw_suffix is None:
                return False
            if agent.status == "RUNNING":
                return (agent.cl_name, agent.raw_suffix) in dismissed_cl_suffixes or (
                    agent.cl_name == "unknown"
                    and agent.raw_suffix in dismissed_suffixes
                )
            return agent.raw_suffix in dismissed_suffixes

        merged: list[Agent] = []
        seen: set[tuple[AgentType, str, str | None]] = set()
        cached_identities = {agent.identity for agent in cached_agents}
        cached_parent_by_suffix = {
            agent.raw_suffix: agent
            for agent in cached_agents
            if agent.raw_suffix is not None and not agent.is_workflow_child
        }
        cached_parent_suffixes = set(cached_parent_by_suffix)
        incoming_parent_suffixes = {
            agent.raw_suffix
            for agent in prep.filtered_agents
            if agent.raw_suffix is not None and not agent.is_workflow_child
        }
        known_parent_suffixes = cached_parent_suffixes | incoming_parent_suffixes
        new_roots: list[Agent] = []
        new_children_by_parent: dict[str, list[Agent]] = {}

        def can_canonical_dedup_running_shadow(agent: Agent) -> bool:
            """Whether loader-level RUNNING↔WORKFLOW dedup can handle this row."""
            cached_parent = (
                cached_parent_by_suffix.get(agent.raw_suffix)
                if agent.raw_suffix is not None
                else None
            )
            return (
                agent.agent_type == AgentType.RUNNING
                and cached_parent is not None
                and cached_parent.agent_type == AgentType.WORKFLOW
                and agent.workflow is not None
                and (
                    agent.workflow.startswith("ace(run)")
                    or agent.workflow == "ace-run"
                    or agent.workflow == "run"
                )
            )

        # Newly discovered Tier 1 rows are usually the newest rows. Keep their
        # relative Tier 1 order while preserving cached parent/child groups.
        for agent in prep.filtered_agents:
            if agent.identity in cached_identities or is_dismissed(agent):
                continue
            if (
                agent.parent_timestamp
                and agent.parent_timestamp in known_parent_suffixes
            ):
                new_children_by_parent.setdefault(agent.parent_timestamp, []).append(
                    agent
                )
                continue
            if (
                agent.raw_suffix is not None
                and not agent.is_workflow_child
                and agent.raw_suffix in cached_parent_suffixes
                and not can_canonical_dedup_running_shadow(agent)
            ):
                continue
            new_roots.append(agent)

        for agent in new_roots:
            if agent.identity in seen:
                continue
            merged.append(agent)
            seen.add(agent.identity)
            if agent.raw_suffix:
                for child in new_children_by_parent.pop(agent.raw_suffix, []):
                    if child.identity in seen:
                        continue
                    merged.append(child)
                    seen.add(child.identity)

        for cached in cached_agents:
            replacement = incoming_by_identity.get(cached.identity, cached)
            if replacement.identity in seen or is_dismissed(replacement):
                continue
            merged.append(replacement)
            seen.add(replacement.identity)
            if replacement.raw_suffix:
                for child in new_children_by_parent.pop(replacement.raw_suffix, []):
                    if child.identity in seen:
                        continue
                    merged.append(child)
                    seen.add(child.identity)

        before_dedup = list(merged)
        merged = dedup_running_vs_workflow(merged)
        merged = dedup_by_pid(merged)
        merged = _reattach_children_after_parent_dedup(before_dedup, merged)

        always_visible = [agent for agent in merged if is_always_visible(agent)]
        hideable = [agent for agent in merged if not is_always_visible(agent)]
        if always_visible and bool(self.hide_non_run_agents) and hideable:
            prep.filtered_agents = always_visible
            prep.hidden_count = len(hideable)
        else:
            prep.filtered_agents = merged
            prep.hidden_count = 0
        prep.has_always_visible = bool(always_visible)
        prep.hideable_agents = hideable

    def _apply_loaded_agents_prepared(
        self,
        prep: PreparedApplyData,
        *,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        load_state: AgentLoadState | None = None,
        persist_dismissed_changes: bool,
    ) -> None:
        """UI-thread step that folds prepared filter output into ``self``.

        Updates the dismissed set with the recovered-bundle and
        auto-dismiss deltas, persists the merged set in a *single*
        :func:`save_dismissed_agents` call (replaces the old per-agent
        write loop), then drops the prepared agent list onto
        ``self._agents`` and runs the finalize pipeline. The fold filter,
        query evaluation, status overrides, registry GC, tab-bar update,
        and panel refresh all happen in :meth:`_finalize_agent_list` on
        this thread.
        """
        # Clear the startup loading indicators (spinner on list panels,
        # dim ellipsis on tab label / info panel) on the first completed
        # load. Safe to call every refresh -- flag stays True and the
        # widget setters are idempotent.
        if not self._agents_first_load_done:
            self._agents_first_load_done = True
            from ...widgets import AgentInfoPanel, AgentList

            try:
                self.query_one("#agent-list-panel", AgentList).loading = False  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                info_panel = self.query_one(  # type: ignore[attr-defined]
                    "#agent-info-panel", AgentInfoPanel
                )
                info_panel.set_loading(False)
            except Exception:
                pass
            self._maybe_end_startup_stopwatch()  # type: ignore[attr-defined]

        if prep.recovered_bundle_identities:
            self._dismissed_agents.update(prep.recovered_bundle_identities)
        if prep.auto_dismissed_identities:
            self._dismissed_agents.update(prep.auto_dismissed_identities)
        if persist_dismissed_changes:
            from ....dismissed_agents import save_dismissed_agents

            save_dismissed_agents(self._dismissed_agents)

        self._preserve_revived_agents_for_incomplete_load(prep, load_state)
        self._merge_incomplete_load_after_complete_history(prep, load_state)

        self._agent_load_state = load_state
        if (
            load_state is not None
            and load_state.needs_full_history_reconcile
            and not getattr(self, "_agents_refresh_pending_full_history", False)
            and not getattr(self, "_agents_refresh_scheduled_full_history", False)
        ):
            self._agents_refresh_pending = True
            self._agents_refresh_pending_full_history = True

        self._dismissed_agent_objects = prep.dismissed_agent_objects
        self._has_always_visible = prep.has_always_visible
        self._hidden_count = prep.hidden_count
        self._hideable_agents = prep.hideable_agents
        self._agents = prep.filtered_agents

        self._finalize_agent_list(
            on_agents_tab, selected_identity, save_unfiltered=True
        )
