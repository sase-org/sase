"""Bulk kill and edit actions for marked agents in the ace TUI app."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ._marking_navigation import AgentMarkNavigationMixin
from ..agent_workflow._types import RelaunchOperation

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ._confirmation_sase_agents import AgentConfirmationSummary


def _gate_is_dismissable(agent: Agent) -> bool:
    if not getattr(agent, "is_gate", False):
        return False
    from sase.gate_shell.state import gate_state_is_terminal

    return bool(gate_state_is_terminal(agent.gate_state) or agent.stop_time)


def _gate_is_waiting(agent: Agent) -> bool:
    return bool(getattr(agent, "is_gate", False) and not _gate_is_dismissable(agent))


def _gate_count_phrase(count: int) -> str:
    noun = "gate" if count == 1 else "gates"
    return f"{count} {noun} waiting for a decision"


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

        The prompt stack mounts immediately after the optimistic kill/dismiss
        rather than waiting for its durable persistence proc to settle. A
        relaunch cleanup barrier holds the eventual launch instead, so a late
        bundle write from the old cleanup still cannot resurrect a name the
        replacement agents are about to reuse.
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
            operation = RelaunchOperation(
                f"bulk kill-and-edit {len(present_agents)} agent(s)"
            )

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
                    if not getattr(agent, "is_gate", False)
                    and agent.pid is not None
                    and agent.status not in DISMISSABLE_STATUSES
                ]
                dismissable = [
                    agent
                    for agent in exact_agents
                    if agent.status in DISMISSABLE_STATUSES
                    or (agent.pid is None and not getattr(agent, "is_gate", False))
                    or _gate_is_dismissable(agent)
                ]

                def mount_prompt_stack() -> None:
                    self._edit_and_relaunch_agents_bulk(  # type: ignore[attr-defined]
                        prompts,
                        first.project_file,
                        first.cl_name,
                        first.is_project_agent,
                        relaunch_operation=operation,
                    )

                from ..agent_workflow._relaunch_barrier import (
                    open_relaunch_cleanup_barrier,
                    settle_relaunch_cleanup_barrier,
                )

                barrier = open_relaunch_cleanup_barrier(
                    self,
                    f"bulk kill-and-edit {len(exact_agents)} agent(s)",
                    operation=operation,
                )
                settle = lambda: settle_relaunch_cleanup_barrier(self, barrier)  # noqa: E731
                if not self._do_bulk_kill_agents(  # type: ignore[attr-defined]
                    killable, dismissable, on_settled=settle
                ):
                    settle()
                    return
                mount_prompt_stack()

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
        on_cancel: Callable[[], None] | None = None,
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

        from ._proc_shell_dismiss import (
            partition_proc_shells,
            proc_shell_count_phrase,
        )

        agents, proc_dismissable, active_proc_shells = partition_proc_shells(agents)
        waiting_gates = [agent for agent in agents if _gate_is_waiting(agent)]
        agents = [agent for agent in agents if agent not in waiting_gates]

        killable: list[Agent] = [
            a
            for a in agents
            if not getattr(a, "is_gate", False)
            and a.pid is not None
            and a.status not in DISMISSABLE_STATUSES
        ]
        dismissable: list[Agent] = [
            a
            for a in agents
            if a.status in DISMISSABLE_STATUSES
            or (a.pid is None and not getattr(a, "is_gate", False))
            or _gate_is_dismissable(a)
        ]

        desc_parts: list[str] = []
        if header:
            desc_parts.append(header)
        from ._confirmation_sase_agents import confirmation_sase_agent_summary

        loaded_agents = self._agents_with_children
        if killable:
            kill_summary: AgentConfirmationSummary = confirmation_sase_agent_summary(
                killable,
                loaded_agents,
                include_running_family_members=True,
            )
            desc_parts.extend(kill_summary.subject_lines("Kill"))
        if dismissable:
            dismiss_summary: AgentConfirmationSummary = confirmation_sase_agent_summary(
                dismissable,
                loaded_agents,
            )
            desc_parts.extend(dismiss_summary.subject_lines("Dismiss"))
        if proc_dismissable:
            desc_parts.append(
                f"Dismiss {proc_shell_count_phrase(len(proc_dismissable))}"
            )
        skip_line = ""
        if active_proc_shells:
            skip_line = "Skipping " + proc_shell_count_phrase(
                len(active_proc_shells), running=True
            )
            desc_parts.append(skip_line)
        if waiting_gates:
            gate_skip_line = "Skipping " + _gate_count_phrase(len(waiting_gates))
            desc_parts.append(gate_skip_line)
            if not skip_line:
                skip_line = gate_skip_line
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmDismissAllModal, ConfirmKillAllModal

        confirm = on_confirm or self._do_bulk_kill_agents  # type: ignore[attr-defined]

        if not killable and not dismissable and not proc_dismissable:
            if skip_line:
                self.notify(skip_line, severity="warning")  # type: ignore[attr-defined]
            if on_cancel is not None:
                on_cancel()
            return

        def on_dismiss(confirmed: bool | None) -> None:
            if not confirmed:
                if on_cancel is not None:
                    on_cancel()
                return
            if killable or dismissable:
                confirm(killable, dismissable)
            if proc_dismissable:
                self._dismiss_proc_shell_rows(proc_dismissable)  # type: ignore[attr-defined]

        if killable:
            self.push_screen(ConfirmKillAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]
        else:
            self.push_screen(ConfirmDismissAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]
