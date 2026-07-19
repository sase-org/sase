"""Fork, resume, and wait-prefill actions for agents."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, cast

from ._fork_scope import (
    AgentPromptTargetScope,
    agent_prompt_target_scope,
    resolve_prompt_target_scope_vcs_tag,
    same_prompt_target_scope,
)
from ._wait_helpers import (
    TabName,
    action_agent_prompt_name,
    resolve_agent_prompt_target_scope,
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

    def _run_prompt_vcs_preparation(
        self,
        resolver: Callable[[], str | None],
        on_complete: Callable[[str | None], None],
        *,
        worker_name: str,
        failure_message: str,
    ) -> None:
        """Resolve disk-backed prompt context off the Textual event loop."""
        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            # Direct mixin harnesses have no Textual worker infrastructure.
            try:
                on_complete(resolver())
            except Exception:
                log.exception("Failed to prepare prompt context")
                self.notify(failure_message, severity="error")  # type: ignore[attr-defined]
            return

        async def prepare_prompt() -> None:
            try:
                vcs_tag = await asyncio.to_thread(resolver)
            except Exception:
                log.exception("Failed to prepare prompt context")
                self.notify(failure_message, severity="error")  # type: ignore[attr-defined]
                return
            on_complete(vcs_tag)

        worker_coro = prepare_prompt()
        try:
            run_worker(
                cast(Any, worker_coro),
                name=worker_name,
                group="agent-prompt-target",
                exclusive=True,
            )
        except Exception:
            worker_coro.close()
            log.exception("Failed to schedule prompt preparation")
            self.notify(failure_message, severity="error")  # type: ignore[attr-defined]

    def _prepare_agent_prompt_target(
        self,
        scope: AgentPromptTargetScope,
        *,
        action: Literal["fork", "wait"],
        revalidate_wait_selection: bool = True,
    ) -> None:
        """Prepare shared VCS context, then finish one target action."""
        agents_snapshot = tuple(self._agents)
        if action == "fork":
            on_complete = lambda vcs_tag: self._complete_agent_fork_scope(  # noqa: E731
                scope,
                vcs_tag,
            )
        else:
            on_complete = lambda vcs_tag: self._complete_agent_wait_scope(  # noqa: E731
                scope,
                vcs_tag,
                revalidate_selection=revalidate_wait_selection,
            )

        self._run_prompt_vcs_preparation(
            lambda: resolve_prompt_target_scope_vcs_tag(scope, agents_snapshot),
            on_complete,
            worker_name=f"agent-{action}-prompt",
            failure_message=f"Unable to prepare {action} prompt",
        )

    def action_fork_agent(self) -> None:
        """Fork the selected agent, clan, or named tribe."""
        if self.current_tab != "agents":
            return

        scope, warning = resolve_agent_prompt_target_scope(self, action="fork")
        if scope is None:
            self.notify(warning or "No fork scope selected", severity="warning")  # type: ignore[attr-defined]
            return

        self._prepare_agent_prompt_target(scope, action="fork")

    def _complete_agent_fork_scope(
        self,
        scope: AgentPromptTargetScope,
        vcs_tag: str | None,
    ) -> None:
        """Revalidate a worker result and open the prefilled prompt bar."""
        current_scope, _warning = resolve_agent_prompt_target_scope(
            self,
            action="fork",
        )
        if current_scope is None or not same_prompt_target_scope(
            scope,
            current_scope,
        ):
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
        """Start a prompt waiting for the selected agent, clan, or tribe."""
        if self.current_tab != "agents":
            return

        if self._marked_agents:
            self._bulk_wait_for_marked_agents()
            return

        scope, warning = resolve_agent_prompt_target_scope(self, action="wait")
        if scope is None:
            self.notify(warning or "No wait target selected", severity="warning")  # type: ignore[attr-defined]
            return

        self._prepare_agent_prompt_target(scope, action="wait")

    def _wait_for_single_agent(
        self,
        agent: Agent,
        *,
        revalidate_selection: bool = True,
    ) -> None:
        """Open the prompt input bar with `%w:<name> ` for a single agent."""
        name = action_agent_prompt_name(agent)
        if not name:
            self.notify("No agent name found", severity="warning")  # type: ignore[attr-defined]
            return
        scope = agent_prompt_target_scope(
            agent,
            name,
            history_fallback="wait",
        )
        self._prepare_agent_prompt_target(
            scope,
            action="wait",
            revalidate_wait_selection=revalidate_selection,
        )

    def _complete_agent_wait_scope(
        self,
        scope: AgentPromptTargetScope,
        vcs_tag: str | None,
        *,
        revalidate_selection: bool = True,
    ) -> None:
        """Revalidate a wait-target worker result and open the prompt bar."""
        if revalidate_selection:
            current_scope, _warning = resolve_agent_prompt_target_scope(
                self,
                action="wait",
            )
            if (
                self._marked_agents
                or current_scope is None
                or not same_prompt_target_scope(scope, current_scope)
            ):
                self.notify(  # type: ignore[attr-defined]
                    "Wait target changed before the prompt opened",
                    severity="warning",
                )
                return

        prefix = f"%w:{scope.prompt_reference} "
        if vcs_tag:
            prefix = f"{vcs_tag}{prefix}"
        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=f"wait({scope.label})",
            history_sort_key=scope.history_sort_key,
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
            self._wait_for_single_agent(named[0], revalidate_selection=False)
            if skipped:
                self.notify(  # type: ignore[attr-defined]
                    f"Skipped {skipped} marked agent(s) with no name",
                    severity="warning",
                )
            return

        names = tuple(
            name for agent in named if (name := action_agent_prompt_name(agent))
        )

        cursor = self._get_selected_agent()  # type: ignore[attr-defined]
        tag_source = cursor if cursor is not None and cursor in named else named[0]
        tag_source_name = action_agent_prompt_name(tag_source)
        assert tag_source_name is not None
        agents_snapshot = tuple(self._agents)
        history_sort_key = (cursor.cl_name if cursor else "wait") or "wait"

        def complete_bulk_wait(vcs_tag: str | None) -> None:
            prefix = f"%w:{','.join(names)} "
            if vcs_tag:
                prefix = f"{vcs_tag}{prefix}"
            self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                initial_text=prefix,
                display_name=f"wait({len(names)} agents)",
                history_sort_key=history_sort_key,
            )
            if skipped:
                self.notify(  # type: ignore[attr-defined]
                    f"Skipped {skipped} marked agent(s) with no name",
                    severity="warning",
                )

        self._run_prompt_vcs_preparation(
            lambda: resolve_agent_vcs_tag(
                tag_source,
                tag_source_name,
                agents_snapshot,
            ),
            complete_bulk_wait,
            worker_name="agent-marked-wait-prompt",
            failure_message="Unable to prepare wait prompt",
        )
