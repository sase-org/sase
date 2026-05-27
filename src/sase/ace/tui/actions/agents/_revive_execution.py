"""Disk mutation and refresh execution for agent revival."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._revive_artifacts import ArtifactRestorationMixin
from ._revive_helpers import (
    is_child_of,
    revived_artifact_dir,
    schedule_revive_full_history_refresh,
)
from ._revive_index import (
    sync_dismissed_agent_artifact_index,
    upsert_agent_artifact_index_artifacts,
)
from ._revive_state import AgentReviveStateMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


class AgentReviveExecutionMixin(AgentReviveStateMixin, ArtifactRestorationMixin):
    """Mixin providing single and batch revive execution."""

    current_tab: str
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]

    def _do_revive_agent(
        self,
        agent: object,
        *,
        selection_scope: object | None = None,
    ) -> None:
        """Revive a dismissed agent by removing it from the dismissed set."""
        from ....dismissed_agents import (
            mark_bundles_revived_by_suffixes,
            save_dismissed_agents,
        )
        from ...models import Agent
        from ...modals import SelectionItem
        from ._revive_log import (
            log_revive_failure,
            log_revive_started,
            log_revive_success,
        )

        if not isinstance(agent, Agent):
            return

        scope = selection_scope if isinstance(selection_scope, SelectionItem) else None
        log_revive_started(agents=[agent], selection_scope=scope)

        child_raw_suffixes: set[str] = set()
        stage = "dismissed_set_update"
        try:
            self._dismissed_agents.discard(agent.identity)
            revived_suffixes: set[str] = set()
            if agent.raw_suffix:
                revived_suffixes.add(agent.raw_suffix)

            # Also revive child steps and follow-up agents (e.g. .code, .q)
            if not agent.is_workflow_child and agent.raw_suffix:
                for dismissed_agent in list(self._dismissed_agent_objects):
                    if is_child_of(dismissed_agent, agent):
                        self._dismissed_agents.discard(dismissed_agent.identity)
                        if dismissed_agent.raw_suffix:
                            child_raw_suffixes.add(dismissed_agent.raw_suffix)
                            revived_suffixes.add(dismissed_agent.raw_suffix)

            # Remove all dismissed aliases that share revived suffixes.
            self._remove_dismissed_aliases_for_suffixes(revived_suffixes)

            if save_dismissed_agents(self._dismissed_agents):
                try:
                    sync_dismissed_agent_artifact_index(self._dismissed_agents)
                except Exception:
                    pass

            stage = "artifact_restore"
            # Restore minimal artifact files so load_all_agents() rediscovers
            # the agent.
            self._restore_agent_artifacts(agent)
            revived_artifact_dirs = [revived_artifact_dir(agent)]

            # Also restore child step / follow-up artifacts for workflow parents
            if not agent.is_workflow_child and agent.raw_suffix:
                for dismissed_agent in list(self._dismissed_agent_objects):
                    if is_child_of(dismissed_agent, agent):
                        self._restore_agent_artifacts(
                            dismissed_agent,
                            parent_artifacts_dir=agent.artifacts_dir,
                        )
                        revived_artifact_dirs.append(
                            revived_artifact_dir(
                                dismissed_agent,
                                parent_artifacts_dir=agent.artifacts_dir,
                            )
                        )
            upsert_agent_artifact_index_artifacts(revived_artifact_dirs)

            stage = "bundle_marking"
            mark_bundles_revived_by_suffixes(revived_suffixes)
            self._record_revived_agent_suffixes(revived_suffixes)
        except Exception as exc:
            log_revive_failure(
                stage=stage,
                agent=agent,
                error=exc,
                selection_scope=scope,
            )
            self.notify(  # type: ignore[attr-defined]
                f"Failed to revive {agent.cl_name}: {exc}", severity="error"
            )
            return

        log_revive_success(
            agent=agent,
            child_suffixes=child_raw_suffixes,
            batch_size=1,
            selection_scope=scope,
        )

        self.notify(f"Revived agent for {agent.cl_name}")  # type: ignore[attr-defined]

        # Patch visible rows from the cached list while the async load
        # reconciles dismissed-set removal off-thread, then run the
        # selection step once the async apply has completed.
        self._refilter_agents()  # type: ignore[attr-defined]

        def _on_revive_loaded(agent: Agent = agent, scope: Any = scope) -> None:
            if self.current_tab != "agents":
                return
            try:
                self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
                self._select_revived_agent(agent)
            except Exception as exc:
                log_revive_failure(
                    stage="refresh_display",
                    agent=agent,
                    error=exc,
                    selection_scope=scope,
                )

        schedule_revive_full_history_refresh(
            self,
            reason="revive_agent_archive_refresh",
            on_complete=_on_revive_loaded,
        )

    def _do_revive_agents(
        self,
        agents: list[Agent],
        *,
        selection_scope: object | None = None,
        group_id: str | None = None,
        group_title: str | None = None,
    ) -> bool:
        """Revive multiple dismissed agents in a single batch.

        Batches disk operations for efficiency: one save_dismissed_agents()
        call and one _load_agents() call instead of N each.
        """
        from ....dismissed_agents import (
            mark_bundles_revived_by_suffixes,
            save_dismissed_agents,
        )
        from ...models import Agent as AgentModel
        from ...modals import SelectionItem
        from ._revive_log import (
            log_revive_failure,
            log_revive_started,
            log_revive_success,
        )

        valid_agents = [a for a in agents if isinstance(a, AgentModel)]
        if not valid_agents:
            return False

        scope = selection_scope if isinstance(selection_scope, SelectionItem) else None
        batch_size = len(valid_agents)
        log_revive_started(
            agents=valid_agents,
            selection_scope=scope,
            group_id=group_id,
            group_title=group_title,
        )

        # Phase 1: Remove all from dismissed set (including children/follow-ups)
        # and collect suffixes for archive revival marks.
        child_suffixes_map: dict[tuple[AgentType, str, str | None], set[str]] = {}
        suffixes_map: dict[tuple[AgentType, str, str | None], set[str]] = {}
        revived_suffixes: set[str] = set()
        stage = "dismissed_set_update"
        try:
            for agent in valid_agents:
                self._dismissed_agents.discard(agent.identity)
                agent_suffixes: set[str] = set()
                if agent.raw_suffix:
                    agent_suffixes.add(agent.raw_suffix)
                child_suffixes: set[str] = set()
                if not agent.is_workflow_child and agent.raw_suffix:
                    for dismissed_agent in list(self._dismissed_agent_objects):
                        if is_child_of(dismissed_agent, agent):
                            self._dismissed_agents.discard(dismissed_agent.identity)
                            if dismissed_agent.raw_suffix:
                                child_suffixes.add(dismissed_agent.raw_suffix)
                                agent_suffixes.add(dismissed_agent.raw_suffix)
                child_suffixes_map[agent.identity] = child_suffixes
                suffixes_map[agent.identity] = agent_suffixes
                revived_suffixes.update(agent_suffixes)

            # Remove all dismissed aliases that share revived suffixes.
            self._remove_dismissed_aliases_for_suffixes(revived_suffixes)

            # Phase 2: Single disk write for dismissed set
            if save_dismissed_agents(self._dismissed_agents):
                try:
                    sync_dismissed_agent_artifact_index(self._dismissed_agents)
                except Exception:
                    pass
        except Exception as exc:
            for agent in valid_agents:
                log_revive_failure(
                    stage=stage,
                    agent=agent,
                    error=exc,
                    batch_size=batch_size,
                    selection_scope=scope,
                    group_id=group_id,
                    group_title=group_title,
                )
            self.notify(  # type: ignore[attr-defined]
                f"Failed to revive {batch_size} agents: {exc}", severity="error"
            )
            return False

        # Phase 3: Restore artifacts. Per-agent failures
        # produce a per-agent ``agent_revive_failed`` event, so partial
        # success leaves an accurate log.
        succeeded: list[Agent] = []
        succeeded_suffixes: set[str] = set()
        revived_artifact_dirs: list[str | None] = []
        for agent in valid_agents:
            per_stage = "artifact_restore"
            try:
                self._restore_agent_artifacts(agent)
                revived_artifact_dirs.append(revived_artifact_dir(agent))
                if not agent.is_workflow_child and agent.raw_suffix:
                    for dismissed_agent in list(self._dismissed_agent_objects):
                        if is_child_of(dismissed_agent, agent):
                            self._restore_agent_artifacts(
                                dismissed_agent,
                                parent_artifacts_dir=agent.artifacts_dir,
                            )
                            revived_artifact_dirs.append(
                                revived_artifact_dir(
                                    dismissed_agent,
                                    parent_artifacts_dir=agent.artifacts_dir,
                                )
                            )
            except Exception as exc:
                log_revive_failure(
                    stage=per_stage,
                    agent=agent,
                    error=exc,
                    batch_size=batch_size,
                    selection_scope=scope,
                    group_id=group_id,
                    group_title=group_title,
                )
                continue
            succeeded.append(agent)
            succeeded_suffixes.update(suffixes_map.get(agent.identity, set()))

        upsert_agent_artifact_index_artifacts(revived_artifact_dirs)

        try:
            mark_bundles_revived_by_suffixes(succeeded_suffixes)
        except Exception as exc:
            for agent in succeeded:
                log_revive_failure(
                    stage="bundle_marking",
                    agent=agent,
                    error=exc,
                    batch_size=batch_size,
                    selection_scope=scope,
                    group_id=group_id,
                    group_title=group_title,
                )
            self.notify(  # type: ignore[attr-defined]
                f"Failed to mark revived archive bundles: {exc}", severity="error"
            )
            return False

        for agent in succeeded:
            log_revive_success(
                agent=agent,
                child_suffixes=child_suffixes_map.get(agent.identity),
                batch_size=batch_size,
                selection_scope=scope,
                group_id=group_id,
                group_title=group_title,
            )

        self._record_revived_agent_suffixes(succeeded_suffixes)

        # Phase 4: Single notification and async refresh
        count = len(valid_agents)
        self.notify(f"Revived {count} agent{'s' if count != 1 else ''}")  # type: ignore[attr-defined]

        revive_candidates = [
            agent for agent in valid_agents if not agent.is_workflow_child
        ]
        if not revive_candidates:
            revive_candidates = list(valid_agents)

        # Patch visible rows from the cached list while the async load
        # reconciles dismissed-set removal off-thread, then run the
        # selection step once the async apply has completed.
        self._refilter_agents()  # type: ignore[attr-defined]

        def _on_revive_loaded(
            candidates: list[Agent] = revive_candidates,
        ) -> None:
            if self.current_tab != "agents":
                return
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
            for candidate in candidates:
                if self._select_revived_agent(candidate):
                    break

        schedule_revive_full_history_refresh(
            self,
            reason="revive_agents_archive_refresh",
            on_complete=_on_revive_loaded,
        )
        return True
