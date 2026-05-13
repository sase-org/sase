"""Agent revival methods for the ace TUI app."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ._revive_artifacts import ArtifactRestorationMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


def _is_child_of(child: Agent, parent: Agent) -> bool:
    """Check if *child* is a workflow step, follow-up, or retry of *parent*.

    Matches workflow step children (``parent_workflow`` set), follow-up
    agents like ``.code`` / ``.q`` (``parent_timestamp`` set,
    ``parent_workflow`` is None), and spawn-on-retry children
    (``retry_of_timestamp`` set).
    """
    # Spawn-on-retry: retry children link to the failing parent via
    # retry_of_timestamp (they are otherwise top-level RUNNING agents).
    if (
        child.retry_of_timestamp
        and parent.raw_suffix
        and child.retry_of_timestamp == parent.raw_suffix
    ):
        return True
    if not child.is_workflow_child or child.parent_timestamp != parent.raw_suffix:
        return False
    # Workflow step children have parent_workflow set; follow-up agents don't.
    return child.parent_workflow is None or child.parent_workflow == parent.workflow


def _merge_dismissed_agents(
    in_memory: Iterable[Agent],
    archive: Iterable[Agent],
) -> list[Agent]:
    """Merge same-session dismissed rows with archive rows, preserving order."""
    merged: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    for agent in (*list(in_memory), *list(archive)):
        if agent.identity in seen:
            continue
        merged.append(agent)
        seen.add(agent.identity)
    return merged


class AgentRevivalMixin(ArtifactRestorationMixin):
    """Mixin providing agent revival (un-dismiss) functionality.

    Overrides action_start_rewind to dispatch to revive flow when on the
    Agents tab, otherwise delegates to the original rewind behavior.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: str
    current_idx: int
    current_attempt_number: int | None
    _agents: list[Agent]
    _current_group_key: tuple[str, ...] | None
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _revived_agent_raw_suffixes: set[str]

    def _select_revived_agent(self, agent: Agent) -> bool:
        """Select *agent* after a revive reload, including its tag panel."""
        target_idx: int | None = None
        for idx, candidate in enumerate(getattr(self, "_agents", [])):
            if candidate.identity == agent.identity or (
                agent.raw_suffix and candidate.raw_suffix == agent.raw_suffix
            ):
                target_idx = idx
                break
        if target_idx is None:
            return False

        if hasattr(self, "_current_group_key"):
            self._current_group_key = None  # type: ignore[attr-defined]
        self.current_idx = target_idx  # type: ignore[attr-defined]
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None  # type: ignore[attr-defined]

        panel_group = getattr(self, "_panel_group", None)
        panel_keys_per_agent = getattr(self, "_panel_keys_per_agent", None)
        if panel_group is None or not callable(panel_keys_per_agent):
            return True

        try:
            keys_per_agent = panel_keys_per_agent()
        except Exception:
            return True
        if not (0 <= target_idx < len(keys_per_agent)):
            return True

        target_panel_key = keys_per_agent[target_idx]
        panel_keys = getattr(panel_group, "panel_keys", [])
        try:
            panel_group.focused_idx = panel_keys.index(target_panel_key)
            return True
        except ValueError:
            pass

        try:
            from ...models.agent_panels import AgentPanelGroup

            self._panel_group = AgentPanelGroup.from_agents(  # type: ignore[attr-defined]
                self._agents,  # type: ignore[attr-defined]
                target_panel_key,
                merge_tag_panels=getattr(self, "_agent_panels_grouped", False),
            )
        except Exception:
            pass
        return True

    def _remove_dismissed_aliases_for_suffixes(self, suffixes: set[str]) -> None:
        """Remove dismissed identities whose raw_suffix matches revived suffixes.

        Loader suppression uses suffix-based matching in addition to exact
        identity checks. Revive must clear all aliases sharing revived suffixes
        so restored artifacts can reappear in the panel.
        """
        if not suffixes:
            return
        self._dismissed_agents = {
            identity
            for identity in self._dismissed_agents
            if identity[2] is None or identity[2] not in suffixes
        }

    def _record_revived_agent_suffixes(self, suffixes: set[str]) -> None:
        """Remember revived suffixes across incomplete Tier 1 refreshes."""
        if not suffixes:
            return
        revived_suffixes = getattr(self, "_revived_agent_raw_suffixes", None)
        if revived_suffixes is None:
            revived_suffixes = set()
            self._revived_agent_raw_suffixes = revived_suffixes
        revived_suffixes.update(suffixes)

    def action_start_rewind(self) -> None:
        """Dispatch R key: revive on Agents tab, rewind on ChangeSpecs tab."""
        if self.current_tab == "agents":
            self._revive_agent()
        else:
            super().action_start_rewind()  # type: ignore[misc]

    def _revive_agent(self) -> None:
        """Show project selection modal, then dismissed agent selection."""
        from ...modals import ProjectSelectModal, ProjectSelectResult, SelectionItem
        from ._revive_log import log_revive_failure

        if not self._dismissed_agent_objects and not self._dismissed_agents:
            log_revive_failure(
                stage="no_dismissed_agents", reason="no_dismissed_agents"
            )
            self.notify("No dismissed agents to revive")  # type: ignore[attr-defined]
            return

        def _on_project_selected(result: ProjectSelectResult | None) -> None:
            if result is None:
                return
            selection = result.selection
            if not isinstance(selection, SelectionItem):
                return
            self._show_dismissed_agents_for_scope(selection)

        self.app.push_screen(  # type: ignore[attr-defined]
            ProjectSelectModal(include_all=True), _on_project_selected
        )

    def _show_dismissed_agents_for_scope(self, selection: object) -> None:
        """Filter dismissed agents by scope and show the selection modal."""
        from ...modals import SelectionItem
        from ...modals.revive_agent_modal import DismissedAgentSelectModal

        if not isinstance(selection, SelectionItem):
            return

        def _filter_for_scope(agents: list[Agent]) -> tuple[list[Agent], list[Agent]]:
            return self._filter_dismissed_agents_for_scope(selection, agents)

        agents = self._dismissed_agent_objects
        filtered, all_in_scope = _filter_for_scope(agents)

        def _on_agents_selected(agents: object) -> None:
            if agents is None:
                return
            if not isinstance(agents, list) or not agents:
                return
            if len(agents) == 1:
                self._do_revive_agent(agents[0], selection_scope=selection)
            else:
                self._do_revive_agents(  # type: ignore[attr-defined]
                    agents, selection_scope=selection
                )

        modal = DismissedAgentSelectModal(
            filtered,
            all_dismissed=all_in_scope,
            loading_archive=True,
        )
        self.app.push_screen(modal, _on_agents_selected)  # type: ignore[attr-defined]

        async def _load_archive_for_modal() -> None:
            archive_agents = await asyncio.to_thread(self._load_dismissed_archive)
            merged = _merge_dismissed_agents(
                self._dismissed_agent_objects, archive_agents
            )
            next_filtered, next_all_in_scope = _filter_for_scope(merged)
            self._dismissed_agent_objects = merged
            try:
                modal.set_agents(
                    next_filtered,
                    all_dismissed=next_all_in_scope,
                    loading_archive=False,
                )
            except Exception:
                pass

        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, _load_archive_for_modal),
                thread=False,
                exclusive=False,
                group="dismissed-archive",
            )
        except Exception:
            self.notify("Failed to load dismissed archive", severity="error")  # type: ignore[attr-defined]

    def _filter_dismissed_agents_for_scope(
        self,
        selection: object,
        agents: list[Agent],
    ) -> tuple[list[Agent], list[Agent]]:
        """Return parent options and all dismissed rows for a selected scope."""
        from ...modals import SelectionItem

        if not isinstance(selection, SelectionItem):
            return [], []
        if selection.item_type == "all":
            filtered = list(agents)
        elif selection.item_type == "home":
            filtered = [a for a in agents if a.cl_name == "~"]
        elif selection.item_type == "project":
            filtered = [
                a
                for a in agents
                if Path(a.project_file).parent.name == selection.project_name
            ]
        elif selection.item_type == "cl":
            filtered = [a for a in agents if a.cl_name == selection.cl_name]
        else:
            return [], []

        # Sort: project-level agents first, then by CL name, then most recent first
        filtered.sort(
            key=lambda a: (
                0 if a.is_project_agent else 1,
                a.cl_name,
                float("inf") if a.start_time is None else -a.start_time.timestamp(),
            )
        )

        # Only show top-level DONE entries (no child steps)
        all_in_scope = list(filtered)
        filtered = [a for a in filtered if not a.is_workflow_child]
        return filtered, all_in_scope

    def _load_dismissed_archive(self) -> list[Agent]:
        """Load dismissed bundles on demand and repair the compact identity index."""
        from ....dismissed_agents import load_dismissed_bundles, save_dismissed_agents

        archive_agents = load_dismissed_bundles()
        found_identities = {agent.identity for agent in archive_agents}
        found_suffixes = {
            agent.raw_suffix for agent in archive_agents if agent.raw_suffix is not None
        }
        in_memory_suffixes = {
            agent.raw_suffix
            for agent in self._dismissed_agent_objects
            if agent.raw_suffix is not None
        }
        next_dismissed = set(self._dismissed_agents)
        next_dismissed.update(found_identities)
        next_dismissed = {
            identity
            for identity in next_dismissed
            if identity[2] is None
            or identity[2] in found_suffixes
            or identity[2] in in_memory_suffixes
        }
        if next_dismissed != self._dismissed_agents:
            self._dismissed_agents = next_dismissed
            save_dismissed_agents(self._dismissed_agents)
        for agent in archive_agents:
            agent._loaded_from_dismissed_bundle = True
        return archive_agents

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
                    if _is_child_of(dismissed_agent, agent):
                        self._dismissed_agents.discard(dismissed_agent.identity)
                        if dismissed_agent.raw_suffix:
                            child_raw_suffixes.add(dismissed_agent.raw_suffix)
                            revived_suffixes.add(dismissed_agent.raw_suffix)

            # Remove all dismissed aliases that share revived suffixes.
            self._remove_dismissed_aliases_for_suffixes(revived_suffixes)

            save_dismissed_agents(self._dismissed_agents)

            stage = "artifact_restore"
            # Restore minimal artifact files so load_all_agents() rediscovers
            # the agent.
            self._restore_agent_artifacts(agent)

            # Also restore child step / follow-up artifacts for workflow parents
            if not agent.is_workflow_child and agent.raw_suffix:
                for dismissed_agent in list(self._dismissed_agent_objects):
                    if _is_child_of(dismissed_agent, agent):
                        self._restore_agent_artifacts(
                            dismissed_agent,
                            parent_artifacts_dir=agent.artifacts_dir,
                        )

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

        stage = "reload"
        try:
            self._load_agents(full_history=True)  # type: ignore[attr-defined]

            if self.current_tab == "agents":
                stage = "refresh_display"
                self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
                self._select_revived_agent(agent)
        except Exception as exc:
            log_revive_failure(
                stage=stage,
                agent=agent,
                error=exc,
                selection_scope=scope,
            )
            return

    def _do_revive_agents(
        self,
        agents: list[Agent],
        *,
        selection_scope: object | None = None,
    ) -> None:
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
            return

        scope = selection_scope if isinstance(selection_scope, SelectionItem) else None
        batch_size = len(valid_agents)
        log_revive_started(agents=valid_agents, selection_scope=scope)

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
                        if _is_child_of(dismissed_agent, agent):
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
            save_dismissed_agents(self._dismissed_agents)
        except Exception as exc:
            for agent in valid_agents:
                log_revive_failure(
                    stage=stage,
                    agent=agent,
                    error=exc,
                    batch_size=batch_size,
                    selection_scope=scope,
                )
            self.notify(  # type: ignore[attr-defined]
                f"Failed to revive {batch_size} agents: {exc}", severity="error"
            )
            return

        # Phase 3: Restore artifacts. Per-agent failures
        # produce a per-agent ``agent_revive_failed`` event, so partial
        # success leaves an accurate log.
        succeeded: list[Agent] = []
        succeeded_suffixes: set[str] = set()
        for agent in valid_agents:
            per_stage = "artifact_restore"
            try:
                self._restore_agent_artifacts(agent)
                if not agent.is_workflow_child and agent.raw_suffix:
                    for dismissed_agent in list(self._dismissed_agent_objects):
                        if _is_child_of(dismissed_agent, agent):
                            self._restore_agent_artifacts(
                                dismissed_agent,
                                parent_artifacts_dir=agent.artifacts_dir,
                            )
            except Exception as exc:
                log_revive_failure(
                    stage=per_stage,
                    agent=agent,
                    error=exc,
                    batch_size=batch_size,
                    selection_scope=scope,
                )
                continue
            succeeded.append(agent)
            succeeded_suffixes.update(suffixes_map.get(agent.identity, set()))

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
                )
            self.notify(  # type: ignore[attr-defined]
                f"Failed to mark revived archive bundles: {exc}", severity="error"
            )
            return

        for agent in succeeded:
            log_revive_success(
                agent=agent,
                child_suffixes=child_suffixes_map.get(agent.identity),
                batch_size=batch_size,
                selection_scope=scope,
            )

        self._record_revived_agent_suffixes(succeeded_suffixes)

        # Phase 4: Single notification and refresh
        count = len(valid_agents)
        self.notify(f"Revived {count} agent{'s' if count != 1 else ''}")  # type: ignore[attr-defined]
        self._load_agents(full_history=True)  # type: ignore[attr-defined]
        if self.current_tab == "agents":
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
            revive_candidates = [
                agent for agent in valid_agents if not agent.is_workflow_child
            ]
            if not revive_candidates:
                revive_candidates = valid_agents
            for agent in revive_candidates:
                if self._select_revived_agent(agent):
                    break
