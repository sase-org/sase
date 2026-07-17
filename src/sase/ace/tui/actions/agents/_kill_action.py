"""Agent kill / dismiss actions for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sase.project_display_names import humanize_cl_name

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_groups import GroupRow
    from ...modals import AgentCleanupAction, AgentCleanupPanelState
    from ...modals.agent_cleanup_modal import AgentCleanupAgentIdentity
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentKillMixin:
    """Mixin providing agent kill / dismiss actions.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _current_group_key: tuple[str, ...] | None

    def action_open_agent_cleanup_panel(self) -> None:
        """Open the Agents cleanup panel, or clear output on the AXE tab."""
        if self.current_tab == "axe":
            self.action_clear_axe_output()  # type: ignore[attr-defined]
            return
        if self.current_tab != "agents":
            return

        from ...modals import AgentCleanupModal, AgentCleanupResult

        def on_dismiss(result: AgentCleanupResult | None) -> None:
            if result is None:
                return
            self._run_agent_cleanup_panel_action(result.action)

        self.push_screen(  # type: ignore[attr-defined]
            AgentCleanupModal(self._build_agent_cleanup_panel_state()),
            on_dismiss,
        )

    def _build_agent_cleanup_panel_state(self) -> AgentCleanupPanelState:
        """Build count state for the cleanup panel shell."""
        from ._core import DISMISSABLE_STATUSES
        from ...modals import AgentCleanupPanelState

        panel_agents = self._agents_in_focused_panel()  # type: ignore[attr-defined]
        all_agents = list(self._agents)

        def running_count(agents: list[Agent]) -> int:
            return sum(
                1
                for agent in agents
                if agent.pid is not None and agent.status not in DISMISSABLE_STATUSES
            )

        def completed_count(agents: list[Agent]) -> int:
            return sum(
                1
                for agent in agents
                if agent.status in DISMISSABLE_STATUSES and agent.raw_suffix is not None
            )

        def failed_count(agents: list[Agent]) -> int:
            return sum(1 for agent in agents if agent.status == "FAILED")

        group_count = 0
        group = self._get_focused_group()
        if group is not None:
            group_count = sum(
                1
                for idx in group.agent_indices
                if 0 <= idx < len(self._agents)
                and not self._agents[idx].is_workflow_child
            )

        return AgentCleanupPanelState(
            focused_panel_label=self._focused_panel_label(),
            panel_running_count=running_count(panel_agents),
            panel_completed_count=completed_count(panel_agents),
            panel_failed_count=failed_count(panel_agents),
            all_running_count=running_count(all_agents),
            all_completed_count=completed_count(all_agents),
            all_failed_count=failed_count(all_agents),
            marked_count=len(self._marked_agents),
            group_count=group_count,
            tag_count=len(self._known_agent_cleanup_tags()),
        )

    def _run_agent_cleanup_panel_action(self, action: AgentCleanupAction) -> None:
        """Route a selected cleanup panel action through existing operations."""
        if action == "dismiss_panel_done":
            self._dismiss_all_done_agents()  # type: ignore[attr-defined]
            return
        if action == "dismiss_all_done":
            self._dismiss_all_done_agents_global()  # type: ignore[attr-defined]
            return
        if action == "kill_panel":
            self._kill_and_dismiss_all_agents()  # type: ignore[attr-defined]
            return
        if action == "kill_all":
            self._kill_and_dismiss_all_agents_global()  # type: ignore[attr-defined]
            return
        if action == "marked":
            self._bulk_kill_marked_agents()  # type: ignore[attr-defined]
            return
        if action == "group":
            group = self._get_focused_group()
            if group is None:
                self.notify("No focused group", severity="warning")  # type: ignore[attr-defined]
                return
            self._bulk_kill_group_agents(group)
            return
        if action == "tag":
            self._open_tag_cleanup_selector()
            return
        if action == "custom":
            self._open_custom_cleanup_selector()
            return
        self.notify("Cleanup option is not available yet", severity="warning")  # type: ignore[attr-defined]

    def _focused_panel_label(self) -> str:
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return "all panels"
        focused_key = panel_group.focused_key
        return "(untagged)" if focused_key is None else f"@{focused_key}"

    def _agent_cleanup_current_scope_targets(self) -> list[Agent]:
        """Return cleanup targets scoped to the current Agents-tab list."""
        from ...models.agent import AgentType

        targets: list[Agent] = []
        seen: set[tuple[AgentType, str, str | None]] = set()

        def add(agent: Agent) -> None:
            if agent.is_clan_container:
                from ._clan_cleanup import clan_members_for_container

                for member in clan_members_for_container(
                    agent, self._agents_with_children
                ):
                    add(member)
                return
            if agent.identity in seen:
                return
            seen.add(agent.identity)
            targets.append(agent)

        current_parent_timestamps = {
            agent.raw_suffix
            for agent in self._agents
            if (
                agent.agent_type == AgentType.WORKFLOW
                and not agent.is_workflow_child
                and agent.raw_suffix is not None
            )
        }
        for agent in self._agents:
            add(agent)
        for agent in self._agents_with_children:
            if (
                agent.is_workflow_child
                and agent.parent_timestamp in current_parent_timestamps
            ):
                add(agent)
        return targets

    def _known_agent_cleanup_tags(self) -> tuple[str, ...]:
        """Return tag names present in the current Agents-tab list."""
        from ...models.agent_panels import effective_tag_per_agent

        tags = {tag for tag in effective_tag_per_agent(self._agents) if tag}
        return tuple(sorted(tags, key=str.lower))

    def _open_tag_cleanup_selector(self) -> None:
        from ...modals import AgentCleanupTagModal, AgentCleanupTagResult

        tags = self._known_agent_cleanup_tags()
        if not tags:
            self.notify("No agent tags found", severity="warning")  # type: ignore[attr-defined]
            return

        def on_dismiss(result: AgentCleanupTagResult | None) -> None:
            if result is None:
                return
            self._present_tag_cleanup_for_tags(result.tags)

        self.push_screen(  # type: ignore[attr-defined]
            AgentCleanupTagModal(
                tags=tags,
                targets=self._agent_cleanup_current_scope_targets(),
            ),
            on_dismiss,
        )

    def _open_custom_cleanup_selector(self) -> None:
        from ...modals import AgentCleanupCustomModal, AgentCleanupCustomResult

        candidates = self._agents_in_focused_panel()  # type: ignore[attr-defined]
        if not candidates:
            self.notify("No agents in focused panel", severity="warning")  # type: ignore[attr-defined]
            return

        def on_dismiss(result: AgentCleanupCustomResult | None) -> None:
            if result is None:
                return
            self._present_custom_cleanup(result.identities)

        self.push_screen(  # type: ignore[attr-defined]
            AgentCleanupCustomModal(
                candidates=candidates,
                targets=list(self._agents_with_children),
                focused_panel_label=self._focused_panel_label(),
            ),
            on_dismiss,
        )

    def _present_tag_cleanup(self, tag: str) -> None:
        self._present_tag_cleanup_for_tags((tag,))

    def _present_tag_cleanup_for_tags(self, tags: tuple[str, ...]) -> None:
        if not tags:
            self.notify("No tags selected", severity="warning")  # type: ignore[attr-defined]
            return

        if len(tags) > 1:
            self._present_multi_tag_cleanup(tags)
            return

        tag = tags[0]
        from sase.core.agent_cleanup_wire import (
            AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            CLEANUP_MODE_KILL_AND_DISMISS,
            CLEANUP_SCOPE_TAG,
            AgentCleanupRequestWire,
        )

        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_TAG,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            tag=tag,
            include_pidless_as_dismissable=True,
        )
        self._present_planned_cleanup(
            request,
            header=f"Tag: @{tag}",
            targets=self._agent_cleanup_current_scope_targets(),
        )

    def _present_multi_tag_cleanup(self, tags: tuple[str, ...]) -> None:
        from sase.core.agent_cleanup_facade import (
            agents_to_cleanup_targets,
            plan_agent_cleanup,
        )
        from sase.core.agent_cleanup_wire import (
            AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            CLEANUP_MODE_KILL_AND_DISMISS,
            CLEANUP_SCOPE_CUSTOM_SELECTION,
            CLEANUP_SCOPE_TAG,
            AgentCleanupIdentityWire,
            AgentCleanupRequestWire,
        )

        cleanup_targets = self._agent_cleanup_current_scope_targets()
        target_wires = agents_to_cleanup_targets(cleanup_targets)
        seen: set[AgentCleanupIdentityWire] = set()
        identities: list[AgentCleanupIdentityWire] = []
        for tag in tags:
            request = AgentCleanupRequestWire(
                schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
                scope=CLEANUP_SCOPE_TAG,
                mode=CLEANUP_MODE_KILL_AND_DISMISS,
                tag=tag,
                include_pidless_as_dismissable=True,
            )
            plan = plan_agent_cleanup(target_wires, request)
            for identity in plan.selected_identities:
                if identity in seen:
                    continue
                seen.add(identity)
                identities.append(identity)

        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_CUSTOM_SELECTION,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            identities=tuple(identities),
            include_pidless_as_dismissable=True,
        )
        tag_label = ", ".join(f"@{tag}" for tag in tags)
        self._present_planned_cleanup(
            request,
            header=f"Tags: {tag_label}",
            targets=cleanup_targets,
        )

    def _present_custom_cleanup(
        self, identities: tuple[AgentCleanupAgentIdentity, ...]
    ) -> None:
        if not identities:
            self.notify("No agents selected", severity="warning")  # type: ignore[attr-defined]
            return

        from sase.core.agent_cleanup_facade import agent_to_cleanup_target
        from sase.core.agent_cleanup_wire import (
            AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            CLEANUP_MODE_KILL_AND_DISMISS,
            CLEANUP_SCOPE_CUSTOM_SELECTION,
            AgentCleanupRequestWire,
        )

        selected = set(identities)
        selected_agents: list[Agent] = []
        seen_selected: set[tuple[AgentType, str, str | None]] = set()
        from ._clan_cleanup import clan_members_for_container

        for agent in self._agents_with_children:
            if agent.identity not in selected:
                continue
            candidates = (
                clan_members_for_container(agent, self._agents_with_children)
                if agent.is_clan_container
                else [agent]
            )
            for candidate in candidates:
                if candidate.identity in seen_selected:
                    continue
                seen_selected.add(candidate.identity)
                selected_agents.append(candidate)
        selected_wire = tuple(
            agent_to_cleanup_target(agent).identity for agent in selected_agents
        )
        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_CUSTOM_SELECTION,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            identities=selected_wire,
            include_pidless_as_dismissable=True,
        )
        self._present_planned_cleanup(request, header="Custom selection")

    def _present_planned_cleanup(
        self,
        request: object,
        *,
        header: str,
        targets: list[Agent] | None = None,
    ) -> None:
        """Preview and confirm a planner-backed cleanup request."""
        from sase.core.agent_cleanup_facade import (
            agent_to_cleanup_target,
            agents_to_cleanup_targets,
            plan_agent_cleanup,
        )

        cleanup_targets = list(
            self._agents_with_children if targets is None else targets
        )
        cleanup_targets = [
            agent for agent in cleanup_targets if not agent.is_clan_container
        ]
        plan = plan_agent_cleanup(agents_to_cleanup_targets(cleanup_targets), request)  # type: ignore[arg-type]
        by_wire_identity = {
            agent_to_cleanup_target(agent).identity: agent for agent in cleanup_targets
        }
        killable = [
            by_wire_identity[item.identity]
            for item in plan.kill_items
            if item.identity in by_wire_identity
        ]
        dismissable = [
            by_wire_identity[item.identity]
            for item in plan.dismiss_items
            if item.identity in by_wire_identity
        ]
        if not killable and not dismissable:
            self.notify("No selected agents can be cleaned up", severity="warning")  # type: ignore[attr-defined]
            return
        self._present_bulk_kill_modal(  # type: ignore[attr-defined]
            [*killable, *dismissable],
            header=header,
        )

    def _notify_no_focused_cleanup_action(
        self, plan: AgentCleanupPlanWire | None, agent: Agent | None = None
    ) -> None:
        skipped_items = getattr(plan, "skipped_items", ()) if plan is not None else ()
        focused_identity = None
        if agent is not None:
            focused_identity = (
                agent.agent_type.value,
                agent.cl_name,
                agent.raw_suffix,
            )
        skipped = None
        if focused_identity is not None:
            skipped = next(
                (
                    item
                    for item in skipped_items
                    if (
                        item.identity.agent_type,
                        item.identity.cl_name,
                        item.identity.raw_suffix,
                    )
                    == focused_identity
                ),
                None,
            )
        if skipped is None:
            skipped = next(iter(skipped_items), None)
        if skipped is None:
            self.notify("No selected agents can be cleaned up", severity="warning")  # type: ignore[attr-defined]
            return
        detail = f": {skipped.detail}" if skipped.detail else ""
        self.notify(  # type: ignore[attr-defined]
            f"Agent cannot be cleaned up ({skipped.reason}{detail})",
            severity="warning",
        )

    def action_kill_agent(self) -> None:
        """Kill or dismiss agent, or toggle/kill axe on AXE tab."""
        if self.current_tab == "changespecs":
            self.action_toggle_hide_submitted()  # type: ignore[attr-defined]
            return
        if self.current_tab == "axe":
            self._toggle_or_kill_axe_view()  # type: ignore[attr-defined]
            return
        if self.current_tab != "agents":
            return

        # Bulk mode: if any marks exist, kill/dismiss the full marked set.
        if self._marked_agents:
            self._bulk_kill_marked_agents()  # type: ignore[attr-defined]
            return

        # Phase 5: focused group banner → bulk kill/dismiss every agent
        # in the group.  Marks take priority above; without marks the
        # banner focus drives a single-confirm bulk action.
        if self._current_group_key is not None:
            group = self._get_focused_group()
            if group is not None:
                self._bulk_kill_group_agents(group)
                return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.is_clan_container:
            from ._clan_cleanup import clan_members_for_container

            members = clan_members_for_container(
                agent,
                self._agents_with_children,
            )
            if not members:
                self.notify("No agents remain in clan", severity="warning")  # type: ignore[attr-defined]
                return
            count = len(members)
            plural = "s" if count != 1 else ""
            self._present_bulk_kill_modal(  # type: ignore[attr-defined]
                members,
                header=f"Clan: {agent.agent_clan} ({count} agent{plural})",
            )
            return

        cleanup_plan = self._plan_focused_agent_cleanup(agent)  # type: ignore[attr-defined]
        if cleanup_plan.dismiss_items and not cleanup_plan.kill_items:
            self._dismiss_planned_agent(agent, cleanup_plan)  # type: ignore[attr-defined]
            return

        if not cleanup_plan.kill_items:
            self._notify_no_focused_cleanup_action(cleanup_plan, agent)
            return

        # Build description for confirmation dialog
        desc_parts = [f"Type: {agent.agent_type.value}"]
        desc_parts.append(
            f"ChangeSpec: {agent.display_name or humanize_cl_name(agent.cl_name)}"
        )
        if agent.workspace_num is not None:
            desc_parts.append(f"Workspace: #{agent.workspace_num}")
        desc_parts.append(f"PID: {agent.pid}")
        agent_description = "\n".join(desc_parts)

        # Show confirmation modal
        from ...modals import ConfirmKillModal

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self._do_kill_agent(agent, cleanup_plan)  # type: ignore[attr-defined]

        self.push_screen(ConfirmKillModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def _get_focused_group(self) -> GroupRow | None:
        """Return the ``GroupRow`` matching ``_current_group_key``, if any.

        Rebuilds the grouping tree at the current fold level and looks up
        the first banner whose ``group_key`` equals ``_current_group_key``
        — the focused-banner key is always populated by the selection
        flow when a banner is the active row.  Returns ``None`` when no
        banner is focused or the key no longer maps to a visible group
        (e.g. the underlying agents have all been dismissed).
        """
        from ._group_focus import get_focused_agent_group

        return get_focused_agent_group(self)

    def _bulk_kill_group_agents(self, group: GroupRow) -> None:
        """Kill / dismiss every (top-level) agent in *group*.

        Routes through the same ``_present_bulk_kill_modal`` flow as the
        marked-set path so the user sees the same confirmation modal,
        per-agent listing, and kill/dismiss split.  Workflow children are
        excluded — killing a parent cascades to its children via
        ``_collect_immediate_kill_identities``, so listing them here
        would only inflate the modal.
        """
        from ._group_focus import top_level_group_agents

        identities = {a.identity for a in top_level_group_agents(group, self._agents)}
        agents = [a for a in self._agents_with_children if a.identity in identities]
        if not agents:
            self.notify("No agents in group", severity="warning")  # type: ignore[attr-defined]
            return

        from ...models.agent_groups import banner_label

        label = banner_label(group)
        count = len(agents)
        plural = "s" if count != 1 else ""
        header = f"Group: {label} ({count} agent{plural})"
        self._present_bulk_kill_modal(agents, header=header)  # type: ignore[attr-defined]
