"""Kill-all and mixed kill/dismiss confirmation actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent


class AgentKillAllActionsMixin:
    """Mixin for kill-all Agents tab actions."""

    def _kill_and_dismiss_all_agents(self) -> None:
        """Kill all running agents and dismiss all done agents (double-confirm)."""
        self._kill_and_dismiss_agents_from(
            self._agents_in_focused_panel(),  # type: ignore[attr-defined]
            empty_message="No agents to kill or dismiss",
        )

    def _kill_and_dismiss_all_agents_global(self) -> None:
        """Kill running and dismiss done agents across all loaded panels."""
        self._kill_and_dismiss_agents_from(
            list(self._agents),  # type: ignore[attr-defined]
            empty_message="No agents to kill or dismiss",
        )

    def _kill_and_dismiss_agents_from(
        self, agents: list[Agent], *, empty_message: str
    ) -> None:
        """Kill running and dismiss done agents from a candidate list."""
        from ._clan_cleanup import expand_clan_containers_for_cleanup
        from ._core import DISMISSABLE_STATUSES

        agents = expand_clan_containers_for_cleanup(
            agents,
            self._agents_with_children,  # type: ignore[attr-defined]
        )

        from ._proc_shell_dismiss import (
            partition_proc_shells,
            proc_shell_count_phrase,
        )

        others, proc_shells, _active = partition_proc_shells(agents)
        killable = [
            a
            for a in others
            if a.pid is not None and a.status not in DISMISSABLE_STATUSES
        ]
        dismissable = [
            a
            for a in others
            if a.status in DISMISSABLE_STATUSES and a.raw_suffix is not None
        ]

        if not killable and not dismissable and not proc_shells:
            self.notify(empty_message, severity="warning")  # type: ignore[attr-defined]
            return

        # Build description showing both groups.
        desc_parts: list[str] = []
        from ._confirmation_sase_agents import confirmation_sase_agent_summary

        loaded_agents = self._agents_with_children  # type: ignore[attr-defined]
        if killable:
            desc_parts.extend(
                confirmation_sase_agent_summary(
                    killable,
                    loaded_agents,
                    include_running_family_members=True,
                ).subject_lines("Kill")
            )
        if dismissable:
            desc_parts.extend(
                confirmation_sase_agent_summary(
                    dismissable,
                    loaded_agents,
                ).subject_lines("Dismiss")
            )
        if proc_shells:
            desc_parts.append(f"Dismiss {proc_shell_count_phrase(len(proc_shells))}")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmKillAllModal

        def on_dismiss(confirmed: bool | None) -> None:
            if not confirmed:
                return
            if killable or dismissable:
                self._do_bulk_kill_agents(killable, dismissable)  # type: ignore[attr-defined]
            if proc_shells:
                self._dismiss_proc_shell_rows(proc_shells)  # type: ignore[attr-defined]

        self.push_screen(ConfirmKillAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]
