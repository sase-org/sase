"""Kill-and-relaunch wait actions for running agents."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from sase.agent.relaunch_prompt import KillAndEditPromptError
from sase.macro.directive_edit import set_prompt_wait_and_queue

from ._wait_helpers import (
    prompt_wait_spec,
    result_has_wait_spec,
    wait_spec_label,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import WaitModalResult


def _prepare_wait_relaunch_prompt(
    agent: Agent,
    agents: Sequence[Agent],
    result: WaitModalResult,
) -> str | None:
    """Return a replacement prompt preserving *agent*'s resolved identity."""
    wait_spec = prompt_wait_spec(result, agent)
    if wait_spec is None:
        return None

    from ..agent_workflow._entry_relaunch import prepare_kill_edit_agent_prompt

    prepared = prepare_kill_edit_agent_prompt(agent, agents)
    if prepared is None:
        return None

    agent_name = agent.agent_name
    if agent_name and not _prompt_forces_name_reuse(prepared):
        from sase.agent.relaunch_prompt import (
            ensure_forced_name_reuse,
            prompt_facing_agent_name,
        )

        facing_name = prompt_facing_agent_name(agent_name)
        try:
            prepared = ensure_forced_name_reuse(prepared, facing_name)
        except ValueError as exc:
            raise KillAndEditPromptError(
                str(exc),
                agent_name=agent_name,
                produced=prepared,
            ) from exc

    return set_prompt_wait_and_queue(prepared, wait_spec)


def _prompt_forces_name_reuse(prompt: str) -> bool:
    """Return whether *prompt* already carries a trusted force-reuse identity."""
    from sase.macro.directives import DirectiveError, extract_prompt_directives

    try:
        _, directives = extract_prompt_directives(prompt)
    except DirectiveError:
        return False
    return directives.name_force_reuse


class AgentWaitRelaunchMixin:
    """Mixin killing and relaunching agents with a replacement wait directive."""

    def _apply_wait_running(self, agent: Agent, result: WaitModalResult) -> None:
        """Kill an active agent and restart with a canonical wait directive."""
        if result.run_now or not result_has_wait_spec(result):
            status = (agent.status or "active").lower()
            self.notify(f"Agent is already {status}", severity="warning")  # type: ignore[attr-defined]
            return
        self._apply_wait_relaunch(agent, result)  # type: ignore[attr-defined]

    def _apply_wait_relaunch(
        self,
        agent: Agent,
        result: WaitModalResult,
    ) -> None:
        """Confirm-kill and relaunch an agent with a replacement wait directive."""
        if prompt_wait_spec(result) is None:
            self.notify("No wait spec to apply", severity="warning")  # type: ignore[attr-defined]
            return

        identity = getattr(agent, "identity", agent)
        loaded_agents = (
            getattr(self, "_agents_with_children", None)
            or getattr(self, "_agents", None)
            or (agent,)
        )

        def on_prompt_resolved(new_prompt: str | None) -> None:
            from ..agent_workflow._entry_relaunch import resolve_agent_identity

            current = resolve_agent_identity(self, identity)
            if current is None:
                self.notify(  # type: ignore[attr-defined]
                    "Selected agent is no longer available; nothing killed",
                    severity="warning",
                )
                return
            if new_prompt is None:
                self.notify("No prompt found for agent", severity="warning")  # type: ignore[attr-defined]
                return
            self._confirm_wait_relaunch(current, identity, result, new_prompt)

        from ..agent_workflow._entry_relaunch import (
            schedule_relaunch_prompt_resolution,
        )

        schedule_relaunch_prompt_resolution(
            self,
            lambda: _prepare_wait_relaunch_prompt(agent, tuple(loaded_agents), result),
            on_prompt_resolved,
            worker_name="agent-wait-relaunch-prompt",
            failure_message="Unable to prepare wait relaunch prompt",
        )

    def _confirm_wait_relaunch(
        self,
        agent: Agent,
        identity: object,
        result: WaitModalResult,
        new_prompt: str,
    ) -> None:
        """Confirm and submit a prepared wait replacement launch."""
        from ...modals import ConfirmKillModal
        from ..agent_workflow._entry_relaunch import resolve_agent_identity
        from ..agent_workflow._relaunch_barrier import (
            open_relaunch_cleanup_barrier,
            settle_relaunch_cleanup_barrier,
        )
        from ..agent_workflow._types import RelaunchOperation
        from ._confirmation_sase_agents import (
            confirmation_sase_agent_entries,
            format_confirmation_entries,
        )

        desc_parts = [f"Kill and restart {wait_spec_label(result)}"]
        desc_parts.append("Sase agent:")
        loaded_agents = (
            getattr(self, "_agents_with_children", None)
            or getattr(self, "_agents", None)
            or [agent]
        )
        desc_parts.extend(
            format_confirmation_entries(
                confirmation_sase_agent_entries(
                    [agent],
                    loaded_agents,
                    include_running_agent_session_members=True,
                )
            )
        )
        if agent.pid:
            desc_parts.append(f"PID: {agent.pid}")
        agent_description = "\n".join(desc_parts)

        def on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            current = resolve_agent_identity(self, identity)
            if current is None:
                self.notify(  # type: ignore[attr-defined]
                    "Selected agent is no longer available; nothing killed",
                    severity="warning",
                )
                return

            operation = RelaunchOperation(f"wait relaunch {current.display_name}")
            barrier = open_relaunch_cleanup_barrier(
                self,
                f"wait relaunch {current.display_name}",
                operation=operation,
            )
            settle = lambda: settle_relaunch_cleanup_barrier(self, barrier)  # noqa: E731
            if not self._do_kill_agent(current, on_settled=settle):  # type: ignore[attr-defined]
                settle()
                return

            from sase.ace.tui.models.agent import is_generated_relaunch_source

            wait_origin = (
                "generated" if is_generated_relaunch_source(current) else "typed"
            )
            self._setup_home_prompt_context(  # type: ignore[attr-defined]
                display_name=current.display_name or current.cl_name,
                history_sort_key=current.cl_name or "wait",
                relaunch_operation=operation,
                prompt_origin=wait_origin,
            )
            self._finish_agent_launch(new_prompt, prompt_origin=wait_origin)  # type: ignore[attr-defined]

        self.push_screen(ConfirmKillModal(agent_description), on_confirm)  # type: ignore[attr-defined]


__all__ = ["AgentWaitRelaunchMixin"]
