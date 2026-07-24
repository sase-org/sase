"""Bulk kill and edit actions for marked agents in the ace TUI app."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ._marking_navigation import AgentMarkNavigationMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


class AgentMarkedKillMixin(AgentMarkNavigationMixin):
    """Kill, dismiss, and edit marked agent sets."""

    def _bulk_kill_marked_agents(self) -> None:
        """Kill / dismiss every marked agent after a single confirmation."""
        if not self._marked_agents:
            return

        marked_agents: list[Agent] = [
            a for a in self._agents_with_children if a.identity in self._marked_agents
        ]
        if not marked_agents:
            self._reset_marked_agents()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        self._present_bulk_kill_modal(marked_agents)

    def _bulk_kill_marked_agents_and_edit(self) -> None:
        """Kill / dismiss marked agents, then edit each one's prompt.

        This is the marked-set branch of ``,x``: when any agent is marked, it
        acts only on the explicitly marked rows, in mark order (rather than the
        single focused row).  Each killed agent's raw prompt is collected up
        front (with the same forced-name-reuse rule as the focused-row path)
        and, on confirmation, seeded into its own prompt pane so the panes
        match the marks one-for-one and follow mark order, not row order.
        """
        if not self._marked_agents:
            self.notify("No agents marked", severity="warning")  # type: ignore[attr-defined]
            return

        # Stale marks are dropped before resolving so panes only ever cover
        # still-live marked rows.
        self._prune_stale_marked_agents()
        marked_agents = self._marked_agents_in_mark_order()
        if not marked_agents:
            self._reset_marked_agents()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        from ..agent_workflow._entry_relaunch import (
            prepare_kill_edit_agent_prompt,
            resolve_agent_identity,
            schedule_relaunch_prompt_resolution,
        )

        identities = tuple(agent.identity for agent in marked_agents)
        agents_snapshot = tuple(self._agents_with_children)

        def resolve_prompts() -> list[str | None]:
            return [
                prepare_kill_edit_agent_prompt(agent, agents_snapshot)
                for agent in marked_agents
            ]

        def on_prompts_resolved(resolved: list[str | None]) -> None:
            current_agents = [
                resolve_agent_identity(self, identity) for identity in identities
            ]
            if any(agent is None for agent in current_agents):
                self.notify(  # type: ignore[attr-defined]
                    "A marked agent is no longer available; nothing killed",
                    severity="warning",
                )
                return
            missing = sum(prompt is None for prompt in resolved)
            if missing:
                suffix = "s" if missing != 1 else ""
                self.notify(  # type: ignore[attr-defined]
                    f"{missing} marked agent{suffix} missing a prompt; nothing killed",
                    severity="warning",
                )
                return

            prompts = [prompt for prompt in resolved if prompt is not None]
            present_agents = [agent for agent in current_agents if agent is not None]
            first = present_agents[0]

            def on_confirm(
                _killable: list[Agent],
                _dismissable: list[Agent],
            ) -> None:
                confirmed_agents = [
                    resolve_agent_identity(self, identity) for identity in identities
                ]
                if any(agent is None for agent in confirmed_agents):
                    self.notify(  # type: ignore[attr-defined]
                        "A marked agent is no longer available; nothing killed",
                        severity="warning",
                    )
                    return
                from ._core import DISMISSABLE_STATUSES

                exact_agents = [
                    agent for agent in confirmed_agents if agent is not None
                ]
                killable = [
                    agent
                    for agent in exact_agents
                    if agent.pid is not None
                    and agent.status not in DISMISSABLE_STATUSES
                ]
                dismissable = [
                    agent
                    for agent in exact_agents
                    if agent.status in DISMISSABLE_STATUSES or agent.pid is None
                ]
                self._do_bulk_kill_agents(killable, dismissable)  # type: ignore[attr-defined]
                self._edit_and_relaunch_agents_bulk(  # type: ignore[attr-defined]
                    prompts,
                    first.project_file,
                    first.cl_name,
                    first.is_project_agent,
                )

            self._present_bulk_kill_modal(present_agents, on_confirm=on_confirm)

        schedule_relaunch_prompt_resolution(
            self,
            resolve_prompts,
            on_prompts_resolved,
            worker_name="marked-agent-relaunch-prompts",
            failure_message="Unable to prepare marked-agent relaunch prompts",
        )

    def _present_bulk_kill_modal(
        self,
        agents: list[Agent],
        *,
        header: str | None = None,
        on_confirm: Callable[[list[Agent], list[Agent]], None] | None = None,
    ) -> None:
        """Show the kill/dismiss confirmation modal for an arbitrary agent set.

        Partitions *agents* into killable (live PID + non-dismissable
        status) and dismissable buckets, builds the per-agent description,
        and pushes the matching ``ConfirmKillAllModal`` /
        ``ConfirmDismissAllModal``.  On confirm, routes through *on_confirm*
        (called with the killable/dismissable buckets), defaulting to the same
        ``_do_bulk_kill_agents`` machinery used by the marked-set path.  The
        kill-and-edit flow passes a wrapper that kills first and then mounts the
        prompt stack.
        """
        from ._clan_cleanup import clan_members_for_container
        from ._core import DISMISSABLE_STATUSES

        # A clan row is a synthetic selection target, never a persistence or
        # process target. Expand it to its real loaded rows and deduplicate in
        # tree order so marked/group cleanup uses the same cascade as focused x.
        expanded_agents: list[Agent] = []
        seen: set[tuple[AgentType, str, str | None]] = set()
        for agent in agents:
            candidates = (
                clan_members_for_container(agent, self._agents_with_children)
                if getattr(agent, "is_clan_container", False)
                else [agent]
            )
            for candidate in candidates:
                if candidate.identity in seen:
                    continue
                seen.add(candidate.identity)
                expanded_agents.append(candidate)
        agents = expanded_agents

        killable: list[Agent] = [
            a
            for a in agents
            if a.pid is not None and a.status not in DISMISSABLE_STATUSES
        ]
        dismissable: list[Agent] = [
            a for a in agents if a.status in DISMISSABLE_STATUSES or a.pid is None
        ]

        desc_parts: list[str] = []
        if header:
            desc_parts.append(header)
        from ._confirmation_lanes import (
            confirmation_lane_entries,
            format_confirmation_entries,
        )

        loaded_agents = self._agents_with_children
        if killable:
            k_count = len(killable)
            k_s = "s" if k_count != 1 else ""
            desc_parts.append(f"Kill: {k_count} running agent{k_s}")
            desc_parts.extend(
                format_confirmation_entries(
                    confirmation_lane_entries(
                        killable,
                        loaded_agents,
                        include_running_family_members=True,
                    )
                )
            )
        if dismissable:
            d_count = len(dismissable)
            d_s = "s" if d_count != 1 else ""
            desc_parts.append(f"Dismiss: {d_count} agent{d_s}")
            desc_parts.extend(
                format_confirmation_entries(
                    confirmation_lane_entries(dismissable, loaded_agents)
                )
            )
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmDismissAllModal, ConfirmKillAllModal

        confirm = on_confirm or self._do_bulk_kill_agents  # type: ignore[attr-defined]

        def on_dismiss(confirmed: bool | None) -> None:
            if not confirmed:
                return
            confirm(killable, dismissable)

        if killable:
            self.push_screen(ConfirmKillAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]
        else:
            self.push_screen(ConfirmDismissAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]
