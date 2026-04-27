"""Agent tagging actions for the ace TUI Agents tab.

Wires the ``t`` keymap to a small modal that sets or unsets the tag on
the currently focused agent (or, if any agent marks exist, on every
marked agent — same precedence rule used elsewhere on the Agents tab).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ...models.agent_pin import DEFAULT_PINNED_TAG

TabName = Literal["changespecs", "agents", "axe"]

__all__ = ["AgentTaggingMixin", "DEFAULT_PINNED_TAG"]

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
        known_tags = sorted(set(store.values()))

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
                current_tag=None,
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
            current_tag=agent.tag,
            known_tags=tuple(known_tags),
            affected=[agent],
            default_tag=DEFAULT_PINNED_TAG,
        )

    def _open_agent_tag_modal(
        self,
        *,
        target_label: str,
        current_tag: str | None,
        known_tags: tuple[str, ...],
        affected: list[Agent],
        default_tag: str | None = None,
    ) -> None:
        from ...modals import AgentTagModal

        def on_dismiss(result: AgentTagModalResult | None) -> None:
            if result is None:
                return
            self._apply_agent_tag_change(result, affected)

        self.push_screen(  # type: ignore[attr-defined]
            AgentTagModal(
                target_label=target_label,
                current_tag=current_tag,
                known_tags=known_tags,
                default_tag=default_tag,
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
            load_agent_tags,
            save_agent_tags,
            set_tag,
            unset_tag,
        )

        store = load_agent_tags()
        changed = 0
        for agent in affected:
            before = store.get(agent.identity)
            if result.action == "set":
                assert result.tag is not None
                set_tag(store, agent.identity, result.tag)
                after: str | None = result.tag
            else:
                unset_tag(store, agent.identity)
                after = None
            if after != before:
                changed += 1
            agent.tag = after

        if changed == 0:
            verb = "set" if result.action == "set" else "unset"
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
            suffix = "agent" if changed == 1 else "agents"
            if result.action == "set":
                assert result.tag is not None
                self.notify(  # type: ignore[attr-defined]
                    f"Set @{result.tag} on {changed} {suffix}",
                )
            else:
                self.notify(  # type: ignore[attr-defined]
                    f"Cleared tag on {changed} {suffix}",
                )
            affected_identities = {agent.identity for agent in affected}
            self._marked_agents -= affected_identities
            self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]

        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
