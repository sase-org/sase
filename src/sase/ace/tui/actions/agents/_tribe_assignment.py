"""Agent tribe-assignment actions for the ace TUI Agents tab.

Wires the ``N`` keymap to a small modal that sets or clears the tribe on
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

from ...models.agent_pin import DEFAULT_PINNED_TRIBE
from ..task_actions import TrackedTaskCompletion, TrackedTaskResult
from ._directive_persistence import (
    AgentDirectivePersistenceResult,
    AgentDirectivePersistenceSpec,
    AgentMetaPatch,
    AgentTribeStorePatch,
    persist_agent_directive_update,
)

TabName = Literal["changespecs", "agents", "axe"]

__all__ = ["AgentTribeAssignmentMixin", "DEFAULT_PINNED_TRIBE"]

if TYPE_CHECKING:
    from ...modals.agent_tribe_modal import AgentTribeModalResult
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


class AgentTribeAssignmentMixin:
    """Mixin providing the agent-tribe modal action (``N`` keymap)."""

    current_tab: TabName
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _marked_agent_order: list[tuple[AgentType, str, str | None]]

    def action_edit_agent_tribe(self) -> None:
        """Open the agent-tribe modal for the focused agent or marked set."""
        if self.current_tab != "agents":
            return

        from sase.ace.agent_tribes import load_agent_tribes

        store = load_agent_tribes()
        known_tribes = sorted(set(store.values()))

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
            self._open_agent_tribe_modal(
                target_label=f"{len(marked)} marked agent(s)",
                current_tribe=None,
                known_tribes=tuple(known_tribes),
                affected=marked,
            )
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        self._open_agent_tribe_modal(
            target_label=agent.display_name,
            current_tribe=agent.tribe,
            known_tribes=tuple(known_tribes),
            affected=[agent],
            default_tribe=DEFAULT_PINNED_TRIBE,
        )

    def _open_agent_tribe_modal(
        self,
        *,
        target_label: str,
        current_tribe: str | None,
        known_tribes: tuple[str, ...],
        affected: list[Agent],
        default_tribe: str | None = None,
    ) -> None:
        from ...modals import AgentTribeModal

        def on_dismiss(result: AgentTribeModalResult | None) -> None:
            if result is None:
                return
            self._apply_agent_tribe_change(result, affected)

        self.push_screen(  # type: ignore[attr-defined]
            AgentTribeModal(
                target_label=target_label,
                current_tribe=current_tribe,
                known_tribes=known_tribes,
                default_tribe=default_tribe,
            ),
            on_dismiss,
        )

    def _apply_agent_tribe_change(
        self,
        result: AgentTribeModalResult,
        affected: list[Agent],
    ) -> None:
        """Persist the requested tribe change for every agent in *affected*."""
        snapshot_agents = getattr(self, "_snapshot_agents_for_local_display", None)
        previous_agents = (
            snapshot_agents() if callable(snapshot_agents) else list(self._agents)
        )
        changed = 0
        affected_identities = {agent.identity for agent in affected}
        prior_tribes = {agent.identity: agent.tribe for agent in affected}
        prior_clan_tribes = {agent.identity: agent.clan_tribe for agent in affected}
        specs: list[AgentDirectivePersistenceSpec] = []
        for agent in affected:
            clan_bound = bool(agent.agent_clan)
            visible_before = agent.clan_tribe if clan_bound else agent.tribe
            if result.action == "set":
                assert result.tribe is not None
                after: str | None = result.tribe
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
                                else {"tribe": after}
                                if after
                                else {}
                            ),
                            remove_keys=(
                                ("clan_tribe",)
                                if clan_bound and after is None
                                # Unset also strips the legacy metadata alias so
                                # a later read cannot resurrect the assignment.
                                else ("tribe", "tag")
                                if after is None
                                else ()
                            ),
                        )
                        if artifacts_dir
                        else None
                    ),
                    tribe_patch=(
                        None
                        if clan_bound
                        else AgentTribeStorePatch(
                            identity=agent.identity,
                            tribe=after,
                        )
                    ),
                )
            )

        if changed == 0:
            verb = "set" if result.action == "set" else "unset"
            self.notify(  # type: ignore[attr-defined]
                f"No tribe {verb} (already in target state)",
                severity="information",
            )
            return

        def _task() -> TrackedTaskResult[list[AgentDirectivePersistenceResult]]:
            payload = [persist_agent_directive_update(spec) for spec in specs]
            suffix = "agent" if changed == 1 else "agents"
            if result.action == "set":
                assert result.tribe is not None
                message = f"Set @{result.tribe} on {changed} {suffix}"
            else:
                message = f"Cleared tribe on {changed} {suffix}"
            return TrackedTaskResult(success=True, message=message, payload=payload)

        def _rollback_visible_tribes() -> None:
            for candidates in (self._agents, self._agents_with_children):
                for candidate in candidates:
                    if candidate.identity in prior_tribes:
                        candidate.tribe = prior_tribes[candidate.identity]
                        candidate.clan_tribe = prior_clan_tribes[candidate.identity]

        def _on_complete(
            completion: TrackedTaskCompletion[list[AgentDirectivePersistenceResult]],
        ) -> None:
            if completion.success:
                return
            _rollback_visible_tribes()
            self.notify(  # type: ignore[attr-defined]
                f"Agent tribe persist failed: {completion.message}",
                severity="error",
            )
            refresh = getattr(self, "_schedule_agents_async_refresh", None)
            if callable(refresh):
                refresh(source="agent-tribe-persist-failed")

        task_info = self._submit_tracked_task(  # type: ignore[attr-defined]
            "agent-directive",
            "agent-tribes",
            "agent-tribes",
            _task,
            display_name=f"Persist tribes: {changed}",
            dedup_key="agent-directive-persist:tribes",
            duplicate_message="A tribe persistence task is already running",
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        if task_info is None:
            return

        for agent in affected:
            after = result.tribe if result.action == "set" else None
            for candidates in (self._agents, self._agents_with_children):
                for candidate in candidates:
                    if candidate.identity == agent.identity:
                        if candidate.agent_clan:
                            candidate.clan_tribe = after
                        else:
                            candidate.tribe = after

        suffix = "agent" if changed == 1 else "agents"
        if result.action == "set":
            assert result.tribe is not None
            self.notify(  # type: ignore[attr-defined]
                f"Set @{result.tribe} on {changed} {suffix}",
            )
        else:
            self.notify(  # type: ignore[attr-defined]
                f"Cleared tribe on {changed} {suffix}",
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
