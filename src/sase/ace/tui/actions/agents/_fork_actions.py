"""Fork, resume, and wait-prefill actions for agents."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from ._fork_scope import AgentForkScope, resolve_fork_scope_vcs_tag, same_fork_scope
from ._wait_helpers import (
    TabName,
    action_agent_prompt_name,
    resolve_agent_fork_scope,
    resolve_agent_vcs_tag,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

log = logging.getLogger(__name__)


class AgentForkActionsMixin:
    """Mixin providing agent fork, resume, and wait-prefill actions."""

    current_tab: TabName
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]

    def action_fork_agent(self) -> None:
        """Fork the selected agent, clan, or named tribe."""
        if self.current_tab != "agents":
            return

        scope, warning = resolve_agent_fork_scope(self)
        if scope is None:
            self.notify(warning or "No fork scope selected", severity="warning")  # type: ignore[attr-defined]
            return

        agents_snapshot = tuple(self._agents)
        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            # Direct mixin harnesses have no Textual worker infrastructure.
            vcs_tag = resolve_fork_scope_vcs_tag(scope, agents_snapshot)
            self._complete_agent_fork_scope(scope, vcs_tag)
            return

        async def prepare_fork_prompt() -> None:
            vcs_tag = await asyncio.to_thread(
                resolve_fork_scope_vcs_tag,
                scope,
                agents_snapshot,
            )
            self._complete_agent_fork_scope(scope, vcs_tag)

        worker_coro = prepare_fork_prompt()
        try:
            run_worker(
                cast(Any, worker_coro),
                name="agent-fork-prompt",
                group="agent-fork-prompt",
                exclusive=True,
            )
        except Exception:
            worker_coro.close()
            log.exception("Failed to schedule fork prompt preparation")
            self.notify("Unable to prepare fork prompt", severity="error")  # type: ignore[attr-defined]

    def _complete_agent_fork_scope(
        self,
        scope: AgentForkScope,
        vcs_tag: str | None,
    ) -> None:
        """Revalidate a worker result and open the prefilled prompt bar."""
        current_scope, _warning = resolve_agent_fork_scope(self)
        if current_scope is None or not same_fork_scope(scope, current_scope):
            self.notify(  # type: ignore[attr-defined]
                "Fork scope changed before the prompt opened",
                severity="warning",
            )
            return

        prefix = f"#fork:{scope.prompt_reference} "
        if vcs_tag:
            prefix = f"{vcs_tag}{prefix}"
        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=f"fork({scope.label})",
            history_sort_key=scope.history_sort_key,
        )

    def action_resume_agent(self) -> None:
        """Compatibility alias for the former Agents-tab continuation action."""
        self.action_fork_agent()

    def action_wait_for_agent(self) -> None:
        """Populate prompt with VCS workflow and %w directive for the selected agent."""
        if self.current_tab != "agents":
            return

        if self._marked_agents:
            self._bulk_wait_for_marked_agents()
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        self._wait_for_single_agent(agent)

    def _wait_for_single_agent(self, agent: Agent) -> None:
        """Open the prompt input bar with `%w:<name> ` for a single agent."""
        name = action_agent_prompt_name(agent)
        if not name:
            self.notify("No agent name found", severity="warning")  # type: ignore[attr-defined]
            return

        prefix = f"%w:{name} "

        vcs_tag = resolve_agent_vcs_tag(agent, name, self._agents)
        if vcs_tag:
            prefix = f"{vcs_tag}{prefix}"

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=f"wait({name})",
            history_sort_key=agent.cl_name or "wait",
        )

    def _bulk_wait_for_marked_agents(self) -> None:
        """Open the prompt input bar with `%w:a,b,c ` for the marked agents."""
        marked: list[Agent] = [
            a for a in self._agents_with_children if a.identity in self._marked_agents
        ]
        named: list[Agent] = [a for a in marked if action_agent_prompt_name(a)]
        skipped = len(marked) - len(named)

        if not named:
            self.notify("No marked agents have a name", severity="warning")  # type: ignore[attr-defined]
            return

        if len(named) == 1:
            self._wait_for_single_agent(named[0])
            if skipped:
                self.notify(  # type: ignore[attr-defined]
                    f"Skipped {skipped} marked agent(s) with no name",
                    severity="warning",
                )
            return

        names = [action_agent_prompt_name(a) for a in named]
        prefix = f"%w:{','.join(n for n in names if n)} "

        cursor = self._get_selected_agent()  # type: ignore[attr-defined]
        tag_source = cursor if cursor is not None and cursor in named else named[0]
        tag_source_name = action_agent_prompt_name(tag_source)
        assert tag_source_name is not None
        vcs_tag = resolve_agent_vcs_tag(tag_source, tag_source_name, self._agents)
        if vcs_tag:
            prefix = f"{vcs_tag}{prefix}"

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=f"wait({len(names)} agents)",
            history_sort_key=(cursor.cl_name if cursor else "wait") or "wait",
        )

        if skipped:
            self.notify(  # type: ignore[attr-defined]
                f"Skipped {skipped} marked agent(s) with no name",
                severity="warning",
            )
