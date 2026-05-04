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


def _build_revive_name_map(
    agents: Iterable[Agent],
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Strip dismissal prefixes for *agents* and return ``({old: new}, taken)``.

    Each agent whose ``agent_name`` carries a ``YYmmdd.`` dismissal prefix is
    mutated in-place to its stripped form. When the stripped name is already
    claimed by an active agent (or by another revive in the same batch), a
    ``<base>_<n>`` dedup'd name is allocated instead and the
    ``(original, allocated)`` pair is appended to the returned ``taken`` list
    so the caller can surface a notification.
    Agents without a dismissal prefix (legacy bundles) are skipped — they
    revive under their current name, mirroring the pre-prefix behaviour.
    """
    from sase.agent.names import (
        allocate_revived_name,
        get_active_agent_names,
        is_dismissed_prefixed,
    )

    name_map: dict[str, str] = {}
    unavailable: list[tuple[str, str]] = []
    reserved = get_active_agent_names()

    for agent in agents:
        old = agent.agent_name
        if not old or not is_dismissed_prefixed(old):
            continue
        new, fallback = allocate_revived_name(old, reserved=reserved)
        if fallback is not None:
            unavailable.append((fallback, new))
        agent.agent_name = new
        name_map[old] = new
    return name_map, unavailable


def _apply_revive_reference_rewrites(
    app: AgentRevivalMixin, name_map: dict[str, str]
) -> None:
    """Rewrite on-disk and in-memory wait/resume references for *name_map*.

    Walks the same artifact tree as the dismissal flow but in reverse
    (``YYmmdd.foo`` → ``foo``) and updates every active agent's
    in-memory ``waiting_for`` so the optimistic UI is consistent before
    the next disk reload.
    """
    if not name_map:
        return
    from sase.agent.dismissed_name_rewrites import rewrite_dismissed_references

    rewrite_dismissed_references(
        name_map,
        in_memory_agents=getattr(app, "_agents_with_children", []),
    )


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
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]

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

    def action_start_rewind(self) -> None:
        """Dispatch R key: revive on Agents tab, rewind on ChangeSpecs tab."""
        if self.current_tab == "agents":
            self._revive_agent()
        else:
            super().action_start_rewind()  # type: ignore[misc]

    def _revive_agent(self) -> None:
        """Show project selection modal, then dismissed agent selection."""
        from ...modals import ProjectSelectModal, ProjectSelectResult, SelectionItem

        if not self._dismissed_agent_objects and not self._dismissed_agents:
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
                self._do_revive_agent(agents[0])
            else:
                self._do_revive_agents(agents)  # type: ignore[attr-defined]

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

    def _do_revive_agent(self, agent: object) -> None:
        """Revive a dismissed agent by removing it from the dismissed set."""
        from ....dismissed_agents import (
            remove_bundle_by_identity,
            save_dismissed_agents,
        )
        from ...models import Agent

        if not isinstance(agent, Agent):
            return

        self._dismissed_agents.discard(agent.identity)
        revived_suffixes: set[str] = set()
        if agent.raw_suffix:
            revived_suffixes.add(agent.raw_suffix)

        # Also revive child steps and follow-up agents (e.g. .code, .q)
        child_raw_suffixes: set[str] = set()
        revival_group: list[Agent] = [agent]
        if not agent.is_workflow_child and agent.raw_suffix:
            for dismissed_agent in list(self._dismissed_agent_objects):
                if _is_child_of(dismissed_agent, agent):
                    self._dismissed_agents.discard(dismissed_agent.identity)
                    revival_group.append(dismissed_agent)
                    if dismissed_agent.raw_suffix:
                        child_raw_suffixes.add(dismissed_agent.raw_suffix)
                        revived_suffixes.add(dismissed_agent.raw_suffix)

        # Remove all dismissed aliases that share revived suffixes.
        self._remove_dismissed_aliases_for_suffixes(revived_suffixes)

        # Strip dismissal prefixes before restoring artifacts so the
        # rewritten markers carry the live names.
        name_map, unavailable = _build_revive_name_map(revival_group)

        save_dismissed_agents(self._dismissed_agents)

        # Restore minimal artifact files so load_all_agents() rediscovers the agent
        self._restore_agent_artifacts(agent)

        # Also restore child step / follow-up artifacts for workflow parents
        if not agent.is_workflow_child and agent.raw_suffix:
            for dismissed_agent in list(self._dismissed_agent_objects):
                if _is_child_of(dismissed_agent, agent):
                    self._restore_agent_artifacts(
                        dismissed_agent,
                        parent_artifacts_dir=agent.artifacts_dir,
                    )

        _apply_revive_reference_rewrites(self, name_map)

        # Clean up the bundle now that artifacts are restored
        remove_bundle_by_identity(agent.identity, child_raw_suffixes=child_raw_suffixes)

        self.notify(f"Revived agent for {agent.cl_name}")  # type: ignore[attr-defined]
        for original, allocated in unavailable:
            self.notify(  # type: ignore[attr-defined]
                f"Original name '{original}' was taken; revived as '{allocated}'",
                severity="warning",
            )
        self._load_agents()  # type: ignore[attr-defined]

        # Auto-select the revived agent in the list
        if self.current_tab == "agents":
            for idx, a in enumerate(self._agents):  # type: ignore[attr-defined]
                if a.identity == agent.identity or (
                    agent.raw_suffix and a.raw_suffix == agent.raw_suffix
                ):
                    self.current_idx = idx  # type: ignore[attr-defined]
                    self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
                    break

    def _do_revive_agents(self, agents: list[Agent]) -> None:
        """Revive multiple dismissed agents in a single batch.

        Batches disk operations for efficiency: one save_dismissed_agents()
        call and one _load_agents() call instead of N each.
        """
        from ....dismissed_agents import (
            remove_bundle_by_identity,
            save_dismissed_agents,
        )
        from ...models import Agent as AgentModel

        valid_agents = [a for a in agents if isinstance(a, AgentModel)]
        if not valid_agents:
            return

        # Phase 1: Remove all from dismissed set (including children/follow-ups)
        # and collect child suffixes for bundle removal
        child_suffixes_map: dict[tuple[AgentType, str, str | None], set[str]] = {}
        revived_suffixes: set[str] = set()
        revival_group: list[AgentModel] = []
        for agent in valid_agents:
            self._dismissed_agents.discard(agent.identity)
            revival_group.append(agent)
            if agent.raw_suffix:
                revived_suffixes.add(agent.raw_suffix)
            child_suffixes: set[str] = set()
            if not agent.is_workflow_child and agent.raw_suffix:
                for dismissed_agent in list(self._dismissed_agent_objects):
                    if _is_child_of(dismissed_agent, agent):
                        self._dismissed_agents.discard(dismissed_agent.identity)
                        revival_group.append(dismissed_agent)
                        if dismissed_agent.raw_suffix:
                            child_suffixes.add(dismissed_agent.raw_suffix)
                            revived_suffixes.add(dismissed_agent.raw_suffix)
            child_suffixes_map[agent.identity] = child_suffixes

        # Remove all dismissed aliases that share revived suffixes.
        self._remove_dismissed_aliases_for_suffixes(revived_suffixes)

        # Strip dismissal prefixes from the full revival group in one pass
        # so collision-free auto-name allocation can see every restored
        # name at once.
        name_map, unavailable = _build_revive_name_map(revival_group)

        # Phase 2: Single disk write for dismissed set
        save_dismissed_agents(self._dismissed_agents)

        # Phase 3: Restore artifacts and clean bundles
        for agent in valid_agents:
            self._restore_agent_artifacts(agent)
            if not agent.is_workflow_child and agent.raw_suffix:
                for dismissed_agent in list(self._dismissed_agent_objects):
                    if _is_child_of(dismissed_agent, agent):
                        self._restore_agent_artifacts(
                            dismissed_agent,
                            parent_artifacts_dir=agent.artifacts_dir,
                        )
            remove_bundle_by_identity(
                agent.identity,
                child_raw_suffixes=child_suffixes_map.get(agent.identity),
            )

        _apply_revive_reference_rewrites(self, name_map)

        # Phase 4: Single notification and refresh
        count = len(valid_agents)
        self.notify(f"Revived {count} agent{'s' if count != 1 else ''}")  # type: ignore[attr-defined]
        for original, allocated in unavailable:
            self.notify(  # type: ignore[attr-defined]
                f"Original name '{original}' was taken; revived as '{allocated}'",
                severity="warning",
            )
        self._load_agents()  # type: ignore[attr-defined]
