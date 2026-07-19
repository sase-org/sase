"""Agent tagging actions for the ace TUI Agents tab.

Wires the ``t`` keymap to a small modal that sets or unsets the tag on
the currently focused agent (or, if any agent marks exist, on every
marked agent — same precedence rule used elsewhere on the Agents tab).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from sase.xprompt.directive_edit import (
    prompt_declares_clan,
    set_prompt_clan_tribe,
    set_prompt_tribe,
)

from ...models.agent_pin import DEFAULT_PINNED_TAG
from ..task_actions import TrackedTaskCompletion, TrackedTaskResult
from ._directive_persistence import (
    AgentDirectivePersistenceResult,
    AgentDirectivePersistenceSpec,
    AgentMetaPatch,
    AgentTagStorePatch,
    persist_agent_directive_update,
)

TabName = Literal["changespecs", "agents", "axe"]

__all__ = ["AgentTaggingMixin", "DEFAULT_PINNED_TAG"]

if TYPE_CHECKING:
    from ...modals.agent_tag_modal import AgentTagModalResult
    from ...models import Agent
    from ...models.agent import AgentType


def _prompt_tribe_mutator(tribe: str | None) -> Callable[[str], str]:
    def _mutate(prompt: str) -> str:
        return set_prompt_tribe(prompt, tribe)

    return _mutate


def _prompt_clan_tribe_mutator(tribe: str | None) -> Callable[[str], str]:
    def _mutate(prompt: str) -> str:
        return set_prompt_clan_tribe(prompt, tribe)

    return _mutate


class AgentTaggingMixin:
    """Mixin providing the agent-tagging modal action (``t`` keymap)."""

    current_tab: TabName
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _marked_agent_order: list[tuple[AgentType, str, str | None]]

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
        snapshot_agents = getattr(self, "_snapshot_agents_for_local_display", None)
        previous_agents = (
            snapshot_agents() if callable(snapshot_agents) else list(self._agents)
        )
        changed = 0
        affected_identities = {agent.identity for agent in affected}
        prior_tags = {agent.identity: agent.tag for agent in affected}
        prior_clan_tribes = {agent.identity: agent.clan_tribe for agent in affected}
        specs: list[AgentDirectivePersistenceSpec] = []
        for agent in affected:
            clan_bound = bool(agent.agent_clan)
            visible_before = agent.clan_tribe if clan_bound else agent.tag
            if result.action == "set":
                assert result.tag is not None
                after: str | None = result.tag
            else:
                after = None

            if after != visible_before:
                changed += 1

            artifacts_dir = agent.get_artifacts_dir()
            if clan_bound and not artifacts_dir:
                self.notify(  # type: ignore[attr-defined]
                    "Cannot edit a synthetic clan row directly; set the tribe "
                    "through a member's %clan(<clan>, tribe=<tribe>) directive.",
                    severity="warning",
                )
                return
            clan_prompt_declares = False
            if clan_bound and artifacts_dir:
                raw_prompt = agent.get_raw_xprompt_content()
                clan_prompt_declares = bool(
                    raw_prompt is not None and prompt_declares_clan(raw_prompt)
                )
            specs.append(
                AgentDirectivePersistenceSpec(
                    artifacts_dir=artifacts_dir,
                    prompt_mutator=(
                        (
                            _prompt_clan_tribe_mutator(after)
                            if clan_prompt_declares
                            else _prompt_tribe_mutator(after)
                            if not clan_bound
                            else None
                        )
                        if artifacts_dir
                        else None
                    ),
                    meta_patch=(
                        AgentMetaPatch(
                            set_values=(
                                {"clan_tribe": after}
                                if clan_bound and after
                                else {"tag": after}
                                if after
                                else {}
                            ),
                            remove_keys=(
                                ("clan_tribe",)
                                if clan_bound and after is None
                                else ("tag",)
                                if after is None
                                else ()
                            ),
                        )
                        if artifacts_dir
                        else None
                    ),
                    tag_patch=(
                        None
                        if clan_bound
                        else AgentTagStorePatch(
                            identity=agent.identity,
                            tag=after,
                        )
                    ),
                )
            )

        if changed == 0:
            verb = "set" if result.action == "set" else "unset"
            self.notify(  # type: ignore[attr-defined]
                f"No tag {verb} (already in target state)",
                severity="information",
            )
            return

        def _task() -> TrackedTaskResult[list[AgentDirectivePersistenceResult]]:
            payload = [persist_agent_directive_update(spec) for spec in specs]
            suffix = "agent" if changed == 1 else "agents"
            if result.action == "set":
                assert result.tag is not None
                message = f"Set @{result.tag} on {changed} {suffix}"
            else:
                message = f"Cleared tag on {changed} {suffix}"
            return TrackedTaskResult(success=True, message=message, payload=payload)

        def _rollback_visible_tags() -> None:
            for candidates in (self._agents, self._agents_with_children):
                for candidate in candidates:
                    if candidate.identity in prior_tags:
                        candidate.tag = prior_tags[candidate.identity]
                        candidate.clan_tribe = prior_clan_tribes[candidate.identity]

        def _on_complete(
            completion: TrackedTaskCompletion[list[AgentDirectivePersistenceResult]],
        ) -> None:
            if completion.success:
                return
            _rollback_visible_tags()
            self.notify(  # type: ignore[attr-defined]
                f"Agent tag persist failed: {completion.message}",
                severity="error",
            )
            refresh = getattr(self, "_schedule_agents_async_refresh", None)
            if callable(refresh):
                refresh(source="agent-tag-persist-failed")

        task_info = self._submit_tracked_task(  # type: ignore[attr-defined]
            "agent-directive",
            "agent-tags",
            "agent-tags",
            _task,
            display_name=f"Persist tags: {changed}",
            dedup_key="agent-directive-persist:tags",
            duplicate_message="A tag persistence task is already running",
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        if task_info is None:
            return

        for agent in affected:
            after = result.tag if result.action == "set" else None
            for candidates in (self._agents, self._agents_with_children):
                for candidate in candidates:
                    if candidate.identity == agent.identity:
                        if candidate.agent_clan:
                            candidate.clan_tribe = after
                        else:
                            candidate.tag = after

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
        self._marked_agents -= affected_identities
        order = getattr(self, "_marked_agent_order", None)
        if order:
            self._marked_agent_order = [
                i for i in order if i not in affected_identities
            ]
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]

        refilter = getattr(self, "_refilter_agents", None)
        if callable(refilter):
            try:
                refilter(previous_agents=previous_agents)
            except TypeError:
                refilter()
        else:
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
