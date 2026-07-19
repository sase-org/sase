"""Clan selection and planning for agent cleanup actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import AgentCleanupClanKey, AgentCleanupClanResult
    from sase.core.agent_cleanup_wire import (
        AgentCleanupPlanWire,
        AgentCleanupTargetWire,
    )


class AgentCleanupClanMixin:
    """Mixin providing planner-backed clan cleanup selection."""

    _agents_with_children: list[Agent]

    def _agent_cleanup_clans_in_focused_panel(
        self, panel_agents: list[Agent] | None = None
    ) -> list[Agent]:
        """Return clan-like container rows in the focused panel."""
        from ._clan_cleanup import clan_members_for_container

        candidates = (
            self._agents_in_focused_panel()  # type: ignore[attr-defined]
            if panel_agents is None
            else panel_agents
        )
        clans: list[Agent] = []
        seen: set[tuple[str, str | None]] = set()
        for agent in candidates:
            members = clan_members_for_container(agent, self._agents_with_children)
            if not agent.is_clan_container and not members:
                continue
            key = self._agent_cleanup_clan_key(agent)
            if key in seen:
                continue
            seen.add(key)
            clans.append(agent)
        return clans

    @staticmethod
    def _agent_cleanup_clan_key(agent: Agent) -> AgentCleanupClanKey:
        label = agent.agent_clan or agent.agent_name or agent.display_name
        generation = (
            agent.agent_clan_generation if agent.agent_clan else agent.raw_suffix
        )
        return (label, generation)

    def _focused_cleanup_clan_key(
        self, clans: list[Agent]
    ) -> AgentCleanupClanKey | None:
        selected = self._get_selected_agent()  # type: ignore[attr-defined]
        if selected is None:
            return None
        from ._clan_cleanup import clan_members_for_container

        for clan in clans:
            if selected is clan or any(
                member.identity == selected.identity
                for member in clan_members_for_container(
                    clan, self._agents_with_children
                )
            ):
                return self._agent_cleanup_clan_key(clan)
        return None

    def _focused_cleanup_clan_label(self, clans: list[Agent]) -> str | None:
        key = self._focused_cleanup_clan_key(clans)
        return None if key is None else key[0]

    def _plan_clan_cleanup_container(
        self,
        container: Agent,
        targets: list[Agent],
        *,
        target_wires: tuple[AgentCleanupTargetWire, ...] | None = None,
    ) -> AgentCleanupPlanWire:
        """Plan one whole container against an already-scoped target snapshot."""
        from sase.core.agent_cleanup_facade import (
            agent_to_cleanup_target,
            agents_to_cleanup_targets,
            plan_agent_cleanup,
        )
        from sase.core.agent_cleanup_wire import (
            AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            CLEANUP_MODE_KILL_AND_DISMISS,
            CLEANUP_SCOPE_CLAN,
            CLEANUP_SCOPE_CUSTOM_SELECTION,
            AgentCleanupRequestWire,
        )

        wires = (
            agents_to_cleanup_targets(targets) if target_wires is None else target_wires
        )
        if container.agent_clan:
            request = AgentCleanupRequestWire(
                schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
                scope=CLEANUP_SCOPE_CLAN,
                mode=CLEANUP_MODE_KILL_AND_DISMISS,
                clan_name=container.agent_clan,
                clan_generation=container.agent_clan_generation,
                include_pidless_as_dismissable=True,
            )
        else:
            from ._clan_cleanup import clan_members_for_container

            request = AgentCleanupRequestWire(
                schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
                scope=CLEANUP_SCOPE_CUSTOM_SELECTION,
                mode=CLEANUP_MODE_KILL_AND_DISMISS,
                identities=tuple(
                    agent_to_cleanup_target(member).identity
                    for member in clan_members_for_container(container, targets)
                ),
                include_pidless_as_dismissable=True,
            )
        return plan_agent_cleanup(wires, request)

    def _open_clan_cleanup_selector(self) -> None:
        from ...modals import AgentCleanupClanModal, AgentCleanupClanResult

        panel_agents = self._agents_in_focused_panel()  # type: ignore[attr-defined]
        clans = self._agent_cleanup_clans_in_focused_panel(panel_agents)
        if not clans:
            self.notify("No clans in focused panel", severity="warning")  # type: ignore[attr-defined]
            return

        initial_clan = self._focused_cleanup_clan_key(clans)

        def on_dismiss(result: AgentCleanupClanResult | None) -> None:
            if result is None:
                return
            self._present_clan_cleanup(result)

        self.push_screen(  # type: ignore[attr-defined]
            AgentCleanupClanModal(
                clans=clans,
                targets=self._agent_cleanup_targets_from_candidates(panel_agents),  # type: ignore[attr-defined]
                focused_panel_label=self._focused_panel_label(),  # type: ignore[attr-defined]
                initial_clan=initial_clan,
            ),
            on_dismiss,
        )

    def _present_clan_cleanup(self, result: AgentCleanupClanResult) -> None:
        """Translate a clan chooser result into the shared planned funnel."""
        if not result.clans and not result.identities:
            self.notify("No clans selected", severity="warning")  # type: ignore[attr-defined]
            return

        from sase.core.agent_cleanup_facade import (
            agent_to_cleanup_target,
            agents_to_cleanup_targets,
        )
        from sase.core.agent_cleanup_wire import (
            AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            CLEANUP_MODE_KILL_AND_DISMISS,
            CLEANUP_SCOPE_CLAN,
            CLEANUP_SCOPE_CUSTOM_SELECTION,
            AgentCleanupIdentityWire,
            AgentCleanupRequestWire,
        )

        panel_agents = self._agents_in_focused_panel()  # type: ignore[attr-defined]
        clans = self._agent_cleanup_clans_in_focused_panel(panel_agents)
        clans_by_key = {self._agent_cleanup_clan_key(clan): clan for clan in clans}
        targets = self._agent_cleanup_targets_from_candidates(panel_agents)  # type: ignore[attr-defined]

        if len(result.clans) == 1 and not result.identities:
            key = result.clans[0]
            container = clans_by_key.get(key)
            if container is not None and container.agent_clan:
                request = AgentCleanupRequestWire(
                    schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
                    scope=CLEANUP_SCOPE_CLAN,
                    mode=CLEANUP_MODE_KILL_AND_DISMISS,
                    clan_name=key[0],
                    clan_generation=key[1],
                    include_pidless_as_dismissable=True,
                )
                self._present_planned_cleanup(  # type: ignore[attr-defined]
                    request,
                    header=f"Clan: {key[0]}",
                    targets=targets,
                )
                return

        target_wires = agents_to_cleanup_targets(targets)
        seen: set[AgentCleanupIdentityWire] = set()
        identities: list[AgentCleanupIdentityWire] = []

        def add(identity: AgentCleanupIdentityWire) -> None:
            if identity in seen:
                return
            seen.add(identity)
            identities.append(identity)

        for key in result.clans:
            container = clans_by_key.get(key)
            if container is None:
                continue
            plan = self._plan_clan_cleanup_container(
                container,
                targets,
                target_wires=target_wires,
            )
            for identity in plan.selected_identities:
                add(identity)

        target_by_identity = {target.identity: target for target in targets}
        selected_clan_keys = set(result.clans)
        from ._clan_cleanup import clan_members_for_container

        for selected_identity in result.identities:
            target = target_by_identity.get(selected_identity)
            if target is None:
                continue
            add(agent_to_cleanup_target(target).identity)
            for clan in clans:
                if any(
                    member.identity == selected_identity
                    for member in clan_members_for_container(clan, targets)
                ):
                    selected_clan_keys.add(self._agent_cleanup_clan_key(clan))
                    break

        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_CUSTOM_SELECTION,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            identities=tuple(identities),
            include_pidless_as_dismissable=True,
        )
        clan_count = max(1, len(selected_clan_keys))
        header = (
            f"Clan: {result.clans[0][0]}"
            if len(result.clans) == 1 and not result.identities
            else f"Clans: {clan_count} selected"
        )
        self._present_planned_cleanup(  # type: ignore[attr-defined]
            request, header=header, targets=targets
        )
