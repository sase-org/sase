"""Agent tagging actions for the ace TUI Agents tab.

Wires the ``t`` keymap to a small modal that adds or removes tags on the
currently focused agent (or, if any agent marks exist, on every marked
agent — same precedence rule used elsewhere on the Agents tab).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

TabName = Literal["changespecs", "agents", "axe"]

if TYPE_CHECKING:
    from ...modals.agent_tag_modal import AgentTagModalResult
    from ...models import Agent
    from ...models.agent import AgentType


class AgentTaggingMixin:
    """Mixin providing the agent-tagging modal action (``t`` keymap)."""

    current_tab: TabName
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]

    def action_add_agent_tag(self) -> None:
        """Open the agent-tag modal for the focused agent or marked set."""
        if self.current_tab != "agents":
            return

        from sase.ace.agent_tags import load_agent_tags

        store = load_agent_tags()
        known_tags = sorted({t for tags in store.values() for t in tags})

        # Bulk path: if marks exist, the modal targets every marked agent.
        if self._marked_agents:
            marked: list[Agent] = [
                a
                for a in self._agents_with_children
                if a.identity in self._marked_agents
            ]
            if not marked:
                self.notify(  # type: ignore[attr-defined]
                    "No marked agents remain",
                    severity="warning",
                )
                return
            self._open_agent_tag_modal(
                target_label=f"{len(marked)} marked agent(s)",
                current_tags=(),
                known_tags=tuple(known_tags),
                affected=marked,
            )
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        self._open_agent_tag_modal(
            target_label=agent.display_name,
            current_tags=tuple(agent.tags),
            known_tags=tuple(known_tags),
            affected=[agent],
        )

    def _open_agent_tag_modal(
        self,
        *,
        target_label: str,
        current_tags: tuple[str, ...],
        known_tags: tuple[str, ...],
        affected: list[Agent],
    ) -> None:
        from ...modals import AgentTagModal

        def on_dismiss(result: AgentTagModalResult | None) -> None:
            if result is None:
                return
            self._apply_agent_tag_change(result, affected)

        self.push_screen(  # type: ignore[attr-defined]
            AgentTagModal(
                target_label=target_label,
                current_tags=current_tags,
                known_tags=known_tags,
            ),
            on_dismiss,
        )

    def _apply_agent_tag_change(
        self,
        result: AgentTagModalResult,
        affected: list[Agent],
    ) -> None:
        """Persist the requested tag change for every agent in *affected*."""
        from sase.ace.agent_tags import (
            add_tags,
            load_agent_tags,
            remove_tags,
            save_agent_tags,
        )

        store = load_agent_tags()
        changed = 0
        for agent in affected:
            before = store.get(agent.identity, ())
            if result.action == "add":
                after = add_tags(store, agent.identity, [result.tag])
            else:
                after = remove_tags(store, agent.identity, [result.tag])
            if after != before:
                changed += 1
            agent.tags = after

        if changed == 0:
            verb = "added" if result.action == "add" else "removed"
            self.notify(  # type: ignore[attr-defined]
                f"No tag {verb} (already in target state)",
                severity="information",
            )
        else:
            if not save_agent_tags(store):
                self.notify(  # type: ignore[attr-defined]
                    "Failed to write agent_tags.json",
                    severity="error",
                )
                return
            verb = "Added" if result.action == "add" else "Removed"
            suffix = "agent" if changed == 1 else "agents"
            self.notify(  # type: ignore[attr-defined]
                f"{verb} @{result.tag} on {changed} {suffix}",
            )

        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
