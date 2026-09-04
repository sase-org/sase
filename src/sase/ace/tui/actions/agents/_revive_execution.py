"""Disk mutation and refresh execution for agent revival."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.core.agent_artifact_paths import resolve_agent_artifact_path

from ._revive_artifacts import ArtifactRestorationMixin
from ._revive_delta import (
    AgentReviveDelta,
    revive_failure_for_agent,
    revive_record_for_agent,
)
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


def _durably_revivable(agent: object) -> bool:
    return bool(getattr(agent, "durably_revivable", True))


def _revive_block_message(agent: object) -> str:
    missing = getattr(agent, "missing_requirements", None) or ()
    if missing:
        return "This archive record is not revivable: missing " + ", ".join(
            str(item) for item in missing
        )
    return "This archive record is not revivable"


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
    ) -> AgentReviveDelta:
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

        epoch_before = int(getattr(self, "_dismiss_revive_epoch", 0))
        dismissed_count_before = len(getattr(self, "_dismissed_agents", ()))
        if not isinstance(agent, Agent):
            return AgentReviveDelta(
                failed=(
                    revive_failure_for_agent(
                        None,
                        stage="input_validation",
                        message="not an Agent",
                    ),
                ),
                dismiss_revive_epoch_before=epoch_before,
                dismiss_revive_epoch_after=epoch_before,
                dismissed_count_before=dismissed_count_before,
                dismissed_count_after=dismissed_count_before,
            )
        if not _durably_revivable(agent):
            message = _revive_block_message(agent)
            self.notify(message, severity="warning")  # type: ignore[attr-defined]
            return AgentReviveDelta(
                failed=(
                    revive_failure_for_agent(
                        agent,
                        stage="capability_check",
                        message=message,
                    ),
                ),
                dismiss_revive_epoch_before=epoch_before,
                dismiss_revive_epoch_after=epoch_before,
                dismissed_count_before=dismissed_count_before,
                dismissed_count_after=dismissed_count_before,
            )

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
        dismissed_index_synced = False
        try:
            # Restore minimal artifact files so load_all_agents() rediscovers
            # the agent.
            self._restore_agent_artifacts(agent)
            agent_artifact_dir = revived_artifact_dir(agent)
            revived_artifact_dirs = [agent_artifact_dir]
            revived_records = [
                revive_record_for_agent(agent, artifact_dir=agent_artifact_dir)
            ]

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
                child_artifact_dir = revived_artifact_dir(
                    dismissed_agent,
                    parent_artifacts_dir=parent_artifacts_dir,
                )
                revived_artifact_dirs.append(child_artifact_dir)
                revived_records.append(
                    revive_record_for_agent(
                        dismissed_agent,
                        artifact_dir=child_artifact_dir,
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
                    # Mark bundle projections visible before syncing the
                    # artifact index so the legacy dismissed view no longer
                    # re-derives these identities.
                    stage = "bundle_marking"
                    mark_bundles_revived_by_suffixes(revived_suffixes)
                    stage = "dismissed_set_update"
                    try:
                        sync_dismissed_agent_artifact_index(
                            self._dismissed_agents,
                            added=(),
                        )
                        dismissed_index_synced = True
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
            return AgentReviveDelta(
                failed=(
                    revive_failure_for_agent(
                        agent,
                        stage=stage,
                        message=str(exc),
                    ),
                ),
                dismiss_revive_epoch_before=epoch_before,
                dismiss_revive_epoch_after=int(
                    getattr(self, "_dismiss_revive_epoch", epoch_before)
                ),
                dismissed_count_before=dismissed_count_before,
                dismissed_count_after=len(self._dismissed_agents),
                dismissed_index_synced=dismissed_index_synced,
            )

        log_revive_success(
            agent=agent,
            child_suffixes=child_raw_suffixes,
            batch_size=1,
            selection_scope=scope,
        )

        self.notify(f"Revived agent for {agent.display_name}")  # type: ignore[attr-defined]

        delta = AgentReviveDelta(
            revived=tuple(revived_records),
            dismiss_revive_epoch_before=epoch_before,
            dismiss_revive_epoch_after=int(
                getattr(self, "_dismiss_revive_epoch", epoch_before)
            ),
            dismissed_count_before=dismissed_count_before,
            dismissed_count_after=len(self._dismissed_agents),
            dismissed_index_synced=dismissed_index_synced,
        )

        # Patch visible rows from the cached list while the async load
        # reconciles dismissed-set removal off-thread, then run the
        # selection step once the async apply has completed.
        if self.current_tab == "agents":
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
        return delta

    def _do_revive_agents(
        self,
        agents: list[Agent],
        *,
        selection_scope: object | None = None,
        group_id: str | None = None,
        group_title: str | None = None,
    ) -> AgentReviveDelta | bool:
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

        epoch_before = int(getattr(self, "_dismiss_revive_epoch", 0))
        dismissed_count_before = len(getattr(self, "_dismissed_agents", ()))
        valid_agents = [a for a in agents if isinstance(a, AgentModel)]
        blocked_agents = [
            agent for agent in valid_agents if not _durably_revivable(agent)
        ]
        if blocked_agents:
            blocked_failed_records = tuple(
                revive_failure_for_agent(
                    agent,
                    stage="capability_check",
                    message=_revive_block_message(agent),
                )
                for agent in blocked_agents
            )
            valid_agents = [
                agent for agent in valid_agents if _durably_revivable(agent)
            ]
        else:
            blocked_failed_records = ()
        if not valid_agents:
            invalid_failed_records = tuple(
                revive_failure_for_agent(
                    agent if isinstance(agent, AgentModel) else None,
                    stage="input_validation",
                    message="not an Agent",
                )
                for agent in agents
                if not isinstance(agent, AgentModel)
            )
            failed = (*invalid_failed_records, *blocked_failed_records)
            if not failed:
                return False
            return AgentReviveDelta(
                failed=failed,
                dismiss_revive_epoch_before=epoch_before,
                dismiss_revive_epoch_after=epoch_before,
                dismissed_count_before=dismissed_count_before,
                dismissed_count_after=dismissed_count_before,
            )

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
        revived_records: list[Any] = []
        failed_records = [
            revive_failure_for_agent(
                agent if isinstance(agent, AgentModel) else None,
                stage="input_validation",
                message="not an Agent",
            )
            for agent in agents
            if not isinstance(agent, AgentModel)
        ]
        failed_records.extend(blocked_failed_records)
        for agent in valid_agents:
            per_stage = "artifact_restore"
            try:
                self._restore_agent_artifacts(agent)
                agent_artifact_dir = revived_artifact_dir(agent)
                revived_artifact_dirs.append(agent_artifact_dir)
                agent_records = [
                    revive_record_for_agent(agent, artifact_dir=agent_artifact_dir)
                ]
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
                                child_artifact_dir := revived_artifact_dir(
                                    dismissed_agent,
                                    parent_artifacts_dir=parent_artifacts_dir,
                                )
                            )
                            agent_records.append(
                                revive_record_for_agent(
                                    dismissed_agent,
                                    artifact_dir=child_artifact_dir,
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
                failed_records.append(
                    revive_failure_for_agent(
                        agent,
                        stage=per_stage,
                        message=str(exc),
                    )
                )
                continue
            succeeded.append(agent)
            revived_records.extend(agent_records)
            succeeded_suffixes.update(suffixes_map.get(agent.identity, set()))

        if not succeeded:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to revive {batch_size} agents", severity="error"
            )
            return AgentReviveDelta(
                failed=tuple(failed_records),
                dismiss_revive_epoch_before=epoch_before,
                dismiss_revive_epoch_after=int(
                    getattr(self, "_dismiss_revive_epoch", epoch_before)
                ),
                dismissed_count_before=dismissed_count_before,
                dismissed_count_after=len(self._dismissed_agents),
            )

        stage = "dismissed_set_update"
        original_dismissed_agents = set(self._dismissed_agents)
        dismissed_index_synced = False
        try:
            for agent in succeeded:
                for identity in identities_map.get(agent.identity, {agent.identity}):
                    self._dismissed_agents.discard(identity)
            # Remove all dismissed aliases that share successfully revived suffixes.
            self._remove_dismissed_aliases_for_suffixes(succeeded_suffixes)

            # Phase 3: Single disk write for dismissed set
            if save_dismissed_agents(self._dismissed_agents):
                # Mark bundle projections visible before syncing the artifact
                # index so the legacy dismissed view stops re-deriving them.
                stage = "bundle_marking"
                mark_bundles_revived_by_suffixes(succeeded_suffixes)
                stage = "dismissed_set_update"
                try:
                    sync_dismissed_agent_artifact_index(
                        self._dismissed_agents,
                        added=(),
                    )
                    dismissed_index_synced = True
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
                failed_records.append(
                    revive_failure_for_agent(
                        agent,
                        stage=stage,
                        message=str(exc),
                    )
                )
            self.notify(  # type: ignore[attr-defined]
                f"Failed to revive {len(succeeded)} agents: {exc}", severity="error"
            )
            return AgentReviveDelta(
                failed=tuple(failed_records),
                dismiss_revive_epoch_before=epoch_before,
                dismiss_revive_epoch_after=int(
                    getattr(self, "_dismiss_revive_epoch", epoch_before)
                ),
                dismissed_count_before=dismissed_count_before,
                dismissed_count_after=len(self._dismissed_agents),
                dismissed_index_synced=dismissed_index_synced,
            )

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

        delta = AgentReviveDelta(
            revived=tuple(revived_records),
            failed=tuple(failed_records),
            dismiss_revive_epoch_before=epoch_before,
            dismiss_revive_epoch_after=int(
                getattr(self, "_dismiss_revive_epoch", epoch_before)
            ),
            dismissed_count_before=dismissed_count_before,
            dismissed_count_after=len(self._dismissed_agents),
            dismissed_index_synced=dismissed_index_synced,
        )

        revive_candidates = [
            agent for agent in succeeded if not agent.is_workflow_child
        ]
        if not revive_candidates:
            revive_candidates = list(succeeded)

        # Patch visible rows from the cached list while the async load
        # reconciles dismissed-set removal off-thread, then run the
        # selection step once the async apply has completed.
        if self.current_tab == "agents":
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
        return delta
