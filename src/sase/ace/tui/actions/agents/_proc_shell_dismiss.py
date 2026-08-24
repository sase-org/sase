"""Dismiss finished stand-alone proc-shell rows from the Agents tab."""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Any, cast

from sase.procs import ACTIVE_PROC_STATUSES, short_proc_id

if TYPE_CHECKING:
    from ...models import Agent

log = logging.getLogger(__name__)


def proc_shell_count_phrase(count: int, *, running: bool = False) -> str:
    """Return a counted ``proc shell`` / ``running proc shell`` noun phrase."""
    noun = "running proc shell" if running else "proc shell"
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def partition_proc_shells(
    agents: Sequence[Agent],
) -> tuple[list[Agent], list[Agent], list[Agent]]:
    """Split *agents* into ``(others, terminal_proc_shells, active_proc_shells)``."""
    others: list[Agent] = []
    terminal: list[Agent] = []
    active: list[Agent] = []
    for agent in agents:
        if not getattr(agent, "is_proc_shell", False):
            others.append(agent)
            continue
        if agent.proc_status in ACTIVE_PROC_STATUSES:
            active.append(agent)
        else:
            terminal.append(agent)
    return others, terminal, active


class ProcShellDismissMixin:
    """Mixin that dismisses finished proc-shell rows as ACE inbox state."""

    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _dismissed_proc_shells: set[str]

    def _dismiss_proc_shell_rows(self, agents: list[Agent]) -> None:
        """Remove finished proc-shell rows from the Agents-tab roster."""
        targets = [
            agent
            for agent in agents
            if getattr(agent, "is_proc_shell", False)
            and agent.proc_id
            and agent.proc_status not in ACTIVE_PROC_STATUSES
        ]
        if not targets:
            self.notify(  # type: ignore[attr-defined]
                "No finished proc shells to dismiss",
                severity="warning",
            )
            return

        proc_ids = [agent.proc_id for agent in targets if agent.proc_id]
        dismissed = set(getattr(self, "_dismissed_proc_shells", ()))
        dismissed.update(proc_ids)
        self._dismissed_proc_shells = dismissed

        capture = getattr(self, "_capture_focused_visible_pos", None)
        prior_pos = capture() if callable(capture) else None
        removed = {agent.identity for agent in targets}
        try_remove = getattr(self, "_try_remove_agent_rows", None)
        fast_path = callable(try_remove) and try_remove(removed)
        self._agents_with_children = [
            agent
            for agent in self._agents_with_children
            if agent.identity not in removed
        ]
        if fast_path:
            finish = getattr(self, "_apply_dismissal_in_memory_fast_finish", None)
            if callable(finish):
                finish(removed, prior_pos=prior_pos)
            else:
                self._agents = [
                    agent for agent in self._agents if agent.identity not in removed
                ]
        else:
            refilter = getattr(self, "_refilter_agents", None)
            if callable(refilter):
                refilter(prior_pos=prior_pos)
            else:
                self._agents = [
                    agent for agent in self._agents if agent.identity not in removed
                ]

        if len(targets) == 1:
            agent = targets[0]
            label = (
                agent.proc_label
                or agent.agent_name
                or short_proc_id(agent.proc_id or "")
            )
            message = f"Dismissed proc shell {label}"
        else:
            message = f"Dismissed {proc_shell_count_phrase(len(targets))}"
        self._notify_proc_shell_dismiss(message)
        self._schedule_persist_dismissed_proc_shells(proc_ids)

    def _notify_proc_shell_dismiss(
        self, message: str, *, severity: str = "information"
    ) -> None:
        notify_after = getattr(self, "_notify_after_refresh", None)
        if callable(notify_after):
            notify_after(message, severity=severity)
            return
        self.notify(message, severity=severity)  # type: ignore[attr-defined]

    def _schedule_persist_dismissed_proc_shells(
        self, proc_ids: Collection[str]
    ) -> None:
        ids = tuple(proc_ids)
        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            return

        async def _worker() -> None:
            await self._run_persist_dismissed_proc_shells(ids)

        try:
            run_worker(
                cast(Any, _worker),
                thread=False,
                exclusive=False,
                group="proc-shell-dismiss",
            )
        except Exception:
            log.exception("Failed to schedule dismissed-proc-shell persistence")

    async def _run_persist_dismissed_proc_shells(
        self, proc_ids: tuple[str, ...]
    ) -> None:
        import asyncio

        from sase.ace.dismissed_proc_shells import record_dismissed_proc_shells

        try:
            ok = await asyncio.to_thread(record_dismissed_proc_shells, proc_ids)
        except Exception:
            log.exception("Dismissed-proc-shell persistence failed")
            ok = False
        if not ok:
            self._notify_proc_shell_dismiss(
                "Could not save dismissed proc shells; they may reappear after restart",
                severity="warning",
            )


__all__ = [
    "ProcShellDismissMixin",
    "partition_proc_shells",
    "proc_shell_count_phrase",
]
