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

        from ..agent_workflow._entry_name_prompts import (
            prepare_kill_and_edit_prompt,
        )

        # Collect raw prompts BEFORE any kill mutates the agent list. Marks are
        # preserved on abort so the user can fix the prompt-less row.
        prompts: list[str] = []
        missing = 0
        for agent in marked_agents:
            raw_prompt = agent.get_raw_xprompt_content()
            if raw_prompt is None:
                missing += 1
                continue
            prompts.append(prepare_kill_and_edit_prompt(raw_prompt, agent.agent_name))
        if missing:
            suffix = "s" if missing != 1 else ""
            self.notify(  # type: ignore[attr-defined]
                f"{missing} marked agent{suffix} missing a prompt; nothing killed",
                severity="warning",
            )
            return

        first = marked_agents[0]

        def on_confirm(killable: list[Agent], dismissable: list[Agent]) -> None:
            self._do_bulk_kill_agents(killable, dismissable)  # type: ignore[attr-defined]
            self._edit_and_relaunch_agents_bulk(  # type: ignore[attr-defined]
                prompts,
                first.project_file,
                first.cl_name,
                first.is_project_agent,
            )

        self._present_bulk_kill_modal(marked_agents, on_confirm=on_confirm)

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
        if killable:
            k_count = len(killable)
            k_s = "s" if k_count != 1 else ""
            desc_parts.append(f"Kill: {k_count} running agent{k_s}")
            for agent in killable:
                name = agent.display_name
                suffix = f" @{agent.agent_name}" if agent.agent_name else ""
                desc_parts.append(f"  {name}{suffix}")
        if dismissable:
            d_count = len(dismissable)
            d_s = "s" if d_count != 1 else ""
            desc_parts.append(f"Dismiss: {d_count} agent{d_s}")
            for agent in dismissable:
                name = agent.display_name
                suffix = f" @{agent.agent_name}" if agent.agent_name else ""
                desc_parts.append(f"  {name}{suffix}")
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
