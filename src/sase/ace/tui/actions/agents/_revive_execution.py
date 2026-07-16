"""Disk mutation and refresh execution for agent revival."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.core.agent_artifact_paths import resolve_agent_artifact_path

from ._revive_artifacts import ArtifactRestorationMixin
from ._revive_helpers import (
    is_child_of,
    revived_artifact_dir,
    schedule_revive_artifact_delta_refresh,
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

        child_agents: list[Agent] = []
        child_raw_suffixes: set[str] = set()
        revived_suffixes: set[str] = set()
        if agent.raw_suffix:
            revived_suffixes.add(agent.raw_suffix)
            if not agent.is_workflow_child:
                child_agents = [
                    dismissed_agent
                    for dismissed_agent in list(self._dismissed_agent_objects)
                    if is_child_of(dismissed_agent, agent)
                ]
                for dismissed_agent in child_agents:
                    if dismissed_agent.raw_suffix:
                        child_raw_suffixes.add(dismissed_agent.raw_suffix)
                        revived_suffixes.add(dismissed_agent.raw_suffix)

        stage = "artifact_restore"
        try:
            # Restore minimal artifact files so load_all_agents() rediscovers
            # the agent.
            self._restore_agent_artifacts(agent)
            revived_artifact_dirs = [revived_artifact_dir(agent)]

            # Also restore child step / follow-up artifacts for workflow parents
            parent_artifacts_dir = (
                str(resolve_agent_artifact_path(agent.artifacts_dir))
                if agent.artifacts_dir
                else None
            )
            for dismissed_agent in child_agents:
                self._restore_agent_artifacts(
                    dismissed_agent,
                    parent_artifacts_dir=parent_artifacts_dir,
                )
                revived_artifact_dirs.append(
                    revived_artifact_dir(
                        dismissed_agent,
                        parent_artifacts_dir=parent_artifacts_dir,
                    )
                )

            stage = "dismissed_set_update"
            original_dismissed_agents = set(self._dismissed_agents)
            try:
                self._dismissed_agents.discard(agent.identity)
                for dismissed_agent in child_agents:
                    self._dismissed_agents.discard(dismissed_agent.identity)

                # Remove all dismissed aliases that share revived suffixes.
                self._remove_dismissed_aliases_for_suffixes(revived_suffixes)

                if save_dismissed_agents(self._dismissed_agents):
                    # Purge the revived agents' dismissed bundles *before*
                    # syncing the artifact index. The dismissed projection
                    # unions the in-memory set with every dismissed-bundle
                    # summary, so a lingering bundle re-hides the revived agent
                    # on the next projection rebuild; purging first also makes
                    # the recorded projection signature reflect the post-purge
                    # bundle index so a later drift rebuild cannot re-add them.
                    stage = "bundle_marking"
                    mark_bundles_revived_by_suffixes(revived_suffixes)
                    stage = "dismissed_set_update"
                    try:
                        sync_dismissed_agent_artifact_index(
                            self._dismissed_agents,
                            added=(),
                        )
                    except Exception:
                        pass
            except Exception:
                self._dismissed_agents = original_dismissed_agents
                raise

            stage = "artifact_index"
            upsert_agent_artifact_index_artifacts(revived_artifact_dirs)
            self._record_revived_agent_suffixes(revived_suffixes)
            bump_epoch = getattr(self, "_bump_dismiss_revive_epoch", None)
            if callable(bump_epoch):
                bump_epoch()
        except Exception as exc:
            log_revive_failure(
                stage=stage,
                agent=agent,
                error=exc,
                selection_scope=scope,
            )
            self.notify(  # type: ignore[attr-defined]
                f"Failed to revive {agent.display_name}: {exc}", severity="error"
            )
            return

        log_revive_success(
            agent=agent,
            child_suffixes=child_raw_suffixes,
            batch_size=1,
            selection_scope=scope,
        )

        self.notify(f"Revived agent for {agent.display_name}")  # type: ignore[attr-defined]

        # Patch visible rows from the cached list while the async load
        # reconciles dismissed-set removal off-thread, then run the
        # selection step once the async apply has completed.
        self._refilter_agents()  # type: ignore[attr-defined]

        revived_agent = agent
        revived_scope: Any = scope

        def _on_revive_loaded() -> None:
            if self.current_tab != "agents":
                return
            try:
                if self._select_revived_agent(revived_agent):
                    self._refresh_agents_display(  # type: ignore[attr-defined]
                        list_changed=False,
                    )
            except Exception as exc:
                log_revive_failure(
                    stage="refresh_display",
                    agent=revived_agent,
                    error=exc,
                    selection_scope=revived_scope,
                )

        schedule_revive_artifact_delta_refresh(
            self,
            revived_artifact_dirs,
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

        # Phase 1: Plan dismissed-set removals (including children/follow-ups)
        # and collect suffixes for archive revival marks. Disk state is not
        # mutated until artifact restoration succeeds.
        child_suffixes_map: dict[tuple[AgentType, str, str | None], set[str]] = {}
        identities_map: dict[
            tuple[AgentType, str, str | None],
            set[tuple[AgentType, str, str | None]],
        ] = {}
        suffixes_map: dict[tuple[AgentType, str, str | None], set[str]] = {}
        for agent in valid_agents:
            identities_to_remove = {agent.identity}
            agent_suffixes: set[str] = set()
            if agent.raw_suffix:
                agent_suffixes.add(agent.raw_suffix)
            child_suffixes: set[str] = set()
            if not agent.is_workflow_child and agent.raw_suffix:
                for dismissed_agent in list(self._dismissed_agent_objects):
                    if is_child_of(dismissed_agent, agent):
                        identities_to_remove.add(dismissed_agent.identity)
                        if dismissed_agent.raw_suffix:
                            child_suffixes.add(dismissed_agent.raw_suffix)
                            agent_suffixes.add(dismissed_agent.raw_suffix)
            child_suffixes_map[agent.identity] = child_suffixes
            identities_map[agent.identity] = identities_to_remove
            suffixes_map[agent.identity] = agent_suffixes

        # Phase 2: Restore artifacts. Per-agent failures
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
                    parent_artifacts_dir = (
                        str(resolve_agent_artifact_path(agent.artifacts_dir))
                        if agent.artifacts_dir
                        else None
                    )
                    for dismissed_agent in list(self._dismissed_agent_objects):
                        if is_child_of(dismissed_agent, agent):
                            self._restore_agent_artifacts(
                                dismissed_agent,
                                parent_artifacts_dir=parent_artifacts_dir,
                            )
                            revived_artifact_dirs.append(
                                revived_artifact_dir(
                                    dismissed_agent,
                                    parent_artifacts_dir=parent_artifacts_dir,
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

        if not succeeded:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to revive {batch_size} agents", severity="error"
            )
            return False

        stage = "dismissed_set_update"
        original_dismissed_agents = set(self._dismissed_agents)
        try:
            for agent in succeeded:
                for identity in identities_map.get(agent.identity, {agent.identity}):
                    self._dismissed_agents.discard(identity)
            # Remove all dismissed aliases that share successfully revived suffixes.
            self._remove_dismissed_aliases_for_suffixes(succeeded_suffixes)

            # Phase 3: Single disk write for dismissed set
            if save_dismissed_agents(self._dismissed_agents):
                # Purge the revived agents' dismissed bundles *before* syncing
                # the artifact index so the projection stops re-deriving the
                # revived identities and the recorded signature reflects the
                # post-purge bundle index (see _do_revive_agent for details).
                stage = "bundle_marking"
                mark_bundles_revived_by_suffixes(succeeded_suffixes)
                stage = "dismissed_set_update"
                try:
                    sync_dismissed_agent_artifact_index(
                        self._dismissed_agents,
                        added=(),
                    )
                except Exception:
                    pass
        except Exception as exc:
            self._dismissed_agents = original_dismissed_agents
            for agent in succeeded:
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
                f"Failed to revive {len(succeeded)} agents: {exc}", severity="error"
            )
            return False

        upsert_agent_artifact_index_artifacts(revived_artifact_dirs)

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
        bump_epoch = getattr(self, "_bump_dismiss_revive_epoch", None)
        if callable(bump_epoch):
            bump_epoch()

        # Phase 4: Single notification and async refresh
        count = len(succeeded)
        self.notify(f"Revived {count} agent{'s' if count != 1 else ''}")  # type: ignore[attr-defined]

        revive_candidates = [
            agent for agent in succeeded if not agent.is_workflow_child
        ]
        if not revive_candidates:
            revive_candidates = list(succeeded)

        # Patch visible rows from the cached list while the async load
        # reconciles dismissed-set removal off-thread, then run the
        # selection step once the async apply has completed.
        self._refilter_agents()  # type: ignore[attr-defined]

        def _on_revive_loaded(
            candidates: list[Agent] = revive_candidates,
        ) -> None:
            if self.current_tab != "agents":
                return
            for candidate in candidates:
                if self._select_revived_agent(candidate):
                    self._refresh_agents_display(  # type: ignore[attr-defined]
                        list_changed=False,
                    )
                    break

        schedule_revive_artifact_delta_refresh(
            self,
            revived_artifact_dirs,
            reason="revive_agents_archive_refresh",
            on_complete=_on_revive_loaded,
        )
        return True
