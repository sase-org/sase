"""Tag and custom-selection flows for agent cleanup actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...modals.agent_cleanup_modal import AgentCleanupAgentIdentity


class AgentCleanupSelectionMixin:
    """Mixin providing tag and custom agent cleanup selection."""

    _agents_with_children: list[Agent]

    def _open_tag_cleanup_selector(self) -> None:
        from ...modals import AgentCleanupTagModal, AgentCleanupTagResult

        tags = self._known_agent_cleanup_tags()  # type: ignore[attr-defined]
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
                targets=self._agent_cleanup_current_scope_targets(),  # type: ignore[attr-defined]
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
                focused_panel_label=self._focused_panel_label(),  # type: ignore[attr-defined]
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
        self._present_planned_cleanup(  # type: ignore[attr-defined]
            request,
            header=f"Tag: @{tag}",
            targets=self._agent_cleanup_current_scope_targets(),  # type: ignore[attr-defined]
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

        cleanup_targets = self._agent_cleanup_current_scope_targets()  # type: ignore[attr-defined]
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
        self._present_planned_cleanup(  # type: ignore[attr-defined]
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
        self._present_planned_cleanup(request, header="Custom selection")  # type: ignore[attr-defined]
