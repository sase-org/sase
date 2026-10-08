"""Wait modal opening and candidate actions for agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    build_agent_completion_candidates,
    visible_agent_completion_agents,
)
from sase.ace.tui.models.agent_session_preview_cache import (
    should_resolve_agent_session_plan_preview,
)

from ._wait_helpers import (
    TabName,
    wait_bead_project_key,
    wait_modal_candidates,
    wait_own_bead_ids,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import WaitModalResult


class AgentWaitModalMixin:
    """Mixin opening the wait modal and sourcing its candidates."""

    current_tab: TabName

    def action_reword(self) -> None:
        """Reword or wait - behavior depends on current tab."""
        if self.current_tab == "agents":
            self._wait_agent()
        else:
            # Call parent implementation for Patches
            super().action_reword()  # type: ignore[misc]

    def _wait_agent(self) -> None:
        """Prompt for an agent name to wait for, or run immediately."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.status not in ("STARTING", "WAITING", "QUEUED", "RUNNING"):
            self.notify(  # type: ignore[attr-defined]
                "Agent is not starting, queued, waiting, or running",
                severity="warning",
            )
            return

        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if not artifacts_dir:
            self.notify("No artifacts directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        from ...modals import WaitModal, WaitModalResult
        from sase.core.wait_epic_follow_view import authored_wait_beads

        is_running = agent.status in {"STARTING", "RUNNING"}
        candidates = wait_modal_candidates(
            agent,
            self._visible_agent_completion_agents(),
        )
        try:
            authored_beads = authored_wait_beads(agent)
        except Exception:  # noqa: BLE001 - prefill falls back to stored beads.
            authored_beads = list(agent.waiting_for_beads)

        def handle_wait_result(result: WaitModalResult | None) -> None:
            if result is None:
                return  # cancelled
            if is_running:
                self._apply_wait_running(agent, result)  # type: ignore[attr-defined]
            else:
                self._apply_wait(artifacts_dir, agent, result)  # type: ignore[attr-defined]

        self.push_screen(  # type: ignore[attr-defined]
            WaitModal(
                current_waiting_for=agent.waiting_for,
                current_waiting_for_beads=authored_beads,
                current_waiting_for_hoods=agent.waiting_for_hoods,
                current_wait_for_epics_of=list(
                    getattr(agent, "wait_for_epics_of", None) or []
                ),
                current_wait_duration=agent.wait_duration,
                current_wait_until=agent.wait_until,
                current_wait_runners=(
                    None
                    if agent.queue_capacity_multiplier is not None
                    else (
                        agent.queue_capacity
                        if agent.queue_capacity_explicit or agent.wait_runners_explicit
                        else None
                    )
                ),
                current_wait_capacity_multiplier=agent.queue_capacity_multiplier,
                current_wait_priority=(
                    agent.wait_priority if agent.wait_priority_explicit else None
                ),
                candidates=candidates,
                is_running=is_running,
                bead_project_key=wait_bead_project_key(agent),
                own_bead_ids=wait_own_bead_ids(agent),
            ),
            handle_wait_result,
        )

    def _visible_wait_candidate_agents(self) -> list[Agent]:
        """Return agents currently visible across all Agents-tab panels."""
        return self._visible_agent_completion_agents()

    def _visible_agent_completion_agents(self) -> list[Agent]:
        """Return agents currently visible across all Agents-tab panels."""
        return visible_agent_completion_agents(self)

    def visible_agent_completion_candidates(
        self,
        *,
        exclude_identity: object | None = None,
    ) -> list[AgentCompletionCandidate]:
        """Return completion candidates sourced from all visible Agents-tab panels."""
        visible_agents = self._visible_agent_completion_agents()
        if any(
            should_resolve_agent_session_plan_preview(agent) for agent in visible_agents
        ):
            schedule = getattr(
                self, "_schedule_agent_session_plan_preview_warmup", None
            )
            if callable(schedule):
                schedule(source="completion")
        return build_agent_completion_candidates(
            visible_agents,
            exclude_identity=exclude_identity,
        )


__all__ = ["AgentWaitModalMixin"]
