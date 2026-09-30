"""Dismiss finished stand-alone named-proc rows from the Agents tab."""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Any, cast

from sase.procs import ACTIVE_PROC_STATUSES, short_proc_id

if TYPE_CHECKING:
    from ...models import Agent

log = logging.getLogger(__name__)


def named_proc_count_phrase(count: int, *, running: bool = False) -> str:
    """Return a counted ``named proc`` / ``running named proc`` noun phrase."""
    noun = "running named proc" if running else "named proc"
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def partition_named_procs(
    agents: Sequence[Agent],
) -> tuple[list[Agent], list[Agent], list[Agent]]:
    """Split *agents* into ``(others, terminal_named_procs, active_named_procs)``."""
    others: list[Agent] = []
    terminal: list[Agent] = []
    active: list[Agent] = []
    for agent in agents:
        if not getattr(agent, "is_named_proc", False):
            others.append(agent)
            continue
        if agent.proc_status in ACTIVE_PROC_STATUSES:
            active.append(agent)
        else:
            terminal.append(agent)
    return others, terminal, active


class NamedProcDismissMixin:
    """Mixin that dismisses finished named-proc rows as ACE inbox state."""

    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _dismissed_named_procs: set[str]

    def _dismiss_named_proc_rows(self, agents: list[Agent]) -> None:
        """Remove finished named-proc rows from the Agents-tab roster."""
        targets = [
            agent
            for agent in agents
            if getattr(agent, "is_named_proc", False)
            and agent.proc_id
            and agent.proc_status not in ACTIVE_PROC_STATUSES
        ]
        if not targets:
            self.notify(  # type: ignore[attr-defined]
                "No finished named procs to dismiss",
                severity="warning",
            )
            return

        proc_ids = [agent.proc_id for agent in targets if agent.proc_id]
        dismissed = set(getattr(self, "_dismissed_named_procs", ()))
        dismissed.update(proc_ids)
        self._dismissed_named_procs = dismissed

        capture = getattr(self, "_capture_focused_visible_pos", None)
        prior_pos = capture() if callable(capture) else None
        removed = {agent.identity for agent in targets}
        record_removals = getattr(self, "record_explicit_removals", None)
        if callable(record_removals):
            record_removals(removed)
        # An explicit dismissal is proof the rows are gone, so a tribe panel
        # that just lost its last node stops being session-sticky.
        retire = getattr(self, "_retire_session_mounted_identities", None)
        panels_retired = bool(callable(retire) and retire(removed))
        try_remove = getattr(self, "_try_remove_agent_rows", None)
        fast_path = callable(try_remove) and try_remove(removed)
        # A clan member's monitor turn carries a tree parent link: removing
        # it re-projects its clan, so the visible list must be rebuilt rather
        # than filtered by identity (which would orphan the container).
        clan_projection_changed = any(
            agent.is_clan_container or agent.tree_parent_key for agent in targets
        )
        from ._roster_generation import set_agents_roster

        set_agents_roster(
            self,
            agents_with_children=[
                agent
                for agent in self._agents_with_children
                if agent.identity not in removed
            ],
        )
        if clan_projection_changed:
            from ...models._agent_tree import project_clan_tree

            set_agents_roster(
                self,
                agents_with_children=project_clan_tree(self._agents_with_children),
            )
            refilter = getattr(self, "_refilter_agents", None)
            if callable(refilter):
                refilter(prior_pos=prior_pos)
            else:
                from ._tab_scope import remove_agents_from_views

                remove_agents_from_views(self, removed, reproject_clan=True)
        elif fast_path:
            finish = getattr(self, "_apply_dismissal_in_memory_fast_finish", None)
            if callable(finish):
                finish(removed, prior_pos=prior_pos, panels_retired=panels_retired)
            else:
                from ._tab_scope import remove_agents_from_views as _remove_views

                _remove_views(self, removed)

        sync_local = getattr(self, "_sync_agents_local_source_from_current", None)
        if callable(sync_local):
            sync_local()
        else:
            refilter = getattr(self, "_refilter_agents", None)
            if callable(refilter):
                refilter(prior_pos=prior_pos)
            else:
                from ._tab_scope import remove_agents_from_views as _remove_views_sync

                _remove_views_sync(self, removed)

        if len(targets) == 1:
            agent = targets[0]
            label = (
                agent.proc_label
                or agent.agent_name
                or short_proc_id(agent.proc_id or "")
            )
            message = f"Dismissed named proc {label}"
        else:
            message = f"Dismissed {named_proc_count_phrase(len(targets))}"
        self._notify_named_proc_dismiss(message)
        self._schedule_persist_dismissed_named_procs(proc_ids)

    def _notify_named_proc_dismiss(
        self, message: str, *, severity: str = "information"
    ) -> None:
        notify_after = getattr(self, "_notify_after_refresh", None)
        if callable(notify_after):
            notify_after(message, severity=severity)
            return
        self.notify(message, severity=severity)  # type: ignore[attr-defined]

    def _schedule_persist_dismissed_named_procs(
        self, proc_ids: Collection[str]
    ) -> None:
        ids = tuple(proc_ids)
        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            return

        async def _worker() -> None:
            await self._run_persist_dismissed_named_procs(ids)

        try:
            run_worker(
                cast(Any, _worker),
                thread=False,
                exclusive=False,
                group="named-proc-dismiss",
            )
        except Exception:
            log.exception("Failed to schedule dismissed-named-proc persistence")

    async def _run_persist_dismissed_named_procs(
        self, proc_ids: tuple[str, ...]
    ) -> None:
        import asyncio

        from sase.ace.dismissed_procs import record_dismissed_procs

        try:
            ok = await asyncio.to_thread(record_dismissed_procs, proc_ids)
        except Exception:
            log.exception("Dismissed-named-proc persistence failed")
            ok = False
        if not ok:
            self._notify_named_proc_dismiss(
                "Could not save dismissed named procs; they may reappear after restart",
                severity="warning",
            )


__all__ = [
    "NamedProcDismissMixin",
    "partition_named_procs",
    "named_proc_count_phrase",
]
