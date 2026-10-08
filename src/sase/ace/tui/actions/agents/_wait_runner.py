"""Parked runner-slot wait persistence for agents."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from sase.agent.status_buckets import runner_slot_display_status

from ..proc_actions import TrackedProcCompletion
from ._wait_helpers import prompt_wait_spec

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import WaitModalResult


def _capacity_wait_label(result: WaitModalResult) -> str:
    """Return the live-runner notification capacity fragment."""
    if result.capacity is not None:
        return f"capacity budget {result.capacity}"
    if result.capacity_multiplier is not None:
        from sase.macro.queue_directive import format_queue_capacity_multiplier

        formatted = format_queue_capacity_multiplier(result.capacity_multiplier)
        label = formatted if formatted is not None else str(result.capacity_multiplier)
        return f"capacity budget {label}"
    return "global runner cap"


class AgentWaitRunnerMixin:
    """Mixin updating a parked slot wait in place for the next runner poll."""

    def _apply_live_runner_wait(
        self,
        artifacts_dir: str,
        agent: Agent,
        result: WaitModalResult,
    ) -> None:
        """Update a parked slot wait in place for the next runner poll."""
        update_wait_priority = (
            result.run_now or result.priority is not None or result.update_priority
        )
        effective_priority = (
            result.priority
            if update_wait_priority
            else agent.wait_priority
            if agent.wait_priority_explicit
            else None
        )
        from ._wait_helpers import authored_result_beads

        wait_spec = prompt_wait_spec(result, agent)
        if wait_spec is not None and effective_priority is not None:
            wait_spec = replace(wait_spec, priority=effective_priority)
        runner_follow = (
            list(wait_spec.epic_follow_agents)
            if wait_spec is not None and wait_spec.epic_follow_agents is not None
            else [
                n
                for n in (getattr(agent, "wait_for_epics_of", None) or [])
                if n in list(result.agents)
            ]
        )
        runner_beads = list(authored_result_beads(result, agent))
        prior_runners = agent.queue_capacity
        prior_explicit = agent.queue_capacity_explicit
        prior_multiplier = agent.queue_capacity_multiplier
        prior_waiting_for = list(agent.waiting_for)
        prior_waiting_for_beads = list(agent.waiting_for_beads)
        prior_waiting_for_hoods = list(agent.waiting_for_hoods)
        prior_wait_for_epics_of = list(getattr(agent, "wait_for_epics_of", None) or [])
        prior_wait_epic_follows = list(getattr(agent, "wait_epic_follows", None) or [])
        prior_wait_duration = agent.wait_duration
        prior_wait_until = agent.wait_until
        prior_priority = agent.wait_priority
        prior_priority_explicit = agent.wait_priority_explicit
        generation = object()
        agent._directive_generation = generation  # type: ignore[attr-defined]
        from ..agent_durable import submit_agent_directive

        def _on_complete(
            completion: TrackedProcCompletion[object],
        ) -> None:
            if completion.collision or completion.success:
                return
            if getattr(agent, "_directive_generation", None) is not generation:
                return
            if prior_multiplier is not None and prior_runners is None:
                agent.set_queue_capacity(
                    None, explicit=prior_explicit, multiplier=prior_multiplier
                )
            else:
                agent.set_queue_capacity(prior_runners, explicit=prior_explicit)
            agent.waiting_for = prior_waiting_for
            agent.waiting_for_beads = prior_waiting_for_beads
            agent.waiting_for_hoods = prior_waiting_for_hoods
            if hasattr(agent, "wait_for_epics_of"):
                agent.wait_for_epics_of = prior_wait_for_epics_of
            if hasattr(agent, "wait_epic_follows"):
                agent.wait_epic_follows = prior_wait_epic_follows
            agent.wait_duration = prior_wait_duration
            agent.wait_until = prior_wait_until
            agent.wait_priority = prior_priority
            agent.wait_priority_explicit = prior_priority_explicit
            self.notify(  # type: ignore[attr-defined]
                f"Runner wait persist failed: {completion.message}",
                severity="error",
            )
            refresh = getattr(self, "_schedule_agents_async_refresh", None)
            if callable(refresh):
                refresh(source="agent-runner-wait-persist-failed")

        wait_payload = None
        if wait_spec is not None:
            wait_payload = {
                "agents": list(wait_spec.agents),
                "beads": list(wait_spec.beads),
                "hoods": list(wait_spec.hoods),
                "priority": wait_spec.priority,
                "capacity": wait_spec.capacity,
                "capacity_multiplier": wait_spec.capacity_multiplier,
                "time_token": wait_spec.time_token,
                "epic_follow_agents": (
                    list(wait_spec.epic_follow_agents)
                    if wait_spec.epic_follow_agents is not None
                    else None
                ),
            }
        submitted = submit_agent_directive(
            self,
            artifacts_dir=artifacts_dir,
            payload={
                "prompt": {"kind": "set_wait", "wait": wait_payload},
                "wait": {
                    "beads": runner_beads,
                    "hoods": list(result.hoods),
                    "names": list(result.agents),
                    "wait_for_epics_of": list(runner_follow),
                    "update_wait_priority": update_wait_priority,
                    "update_wait_runners": True,
                    "wait_priority": result.priority,
                    "wait_runners": result.capacity,
                    "queue_capacity_multiplier": result.capacity_multiplier,
                },
                "waiting": {
                    "beads": runner_beads,
                    "hoods": list(result.hoods),
                    "names": list(result.agents),
                    "wait_for_epics_of": list(runner_follow),
                    "update_wait_priority": update_wait_priority,
                    "update_wait_runners": True,
                    "wait_priority": result.priority,
                    "wait_runners": result.capacity,
                    "queue_capacity_multiplier": result.capacity_multiplier,
                },
            },
            cl_name=agent.cl_name or agent.display_name or "agent",
            display_name=f"Persist runner wait: {agent.display_name}",
            on_complete=_on_complete,
        )
        if not submitted:
            return
        agent.waiting_for = list(result.agents)
        agent.waiting_for_beads = list(runner_beads)
        agent.waiting_for_hoods = list(result.hoods)
        if hasattr(agent, "wait_for_epics_of"):
            agent.wait_for_epics_of = list(runner_follow)
        if hasattr(agent, "wait_epic_follows"):
            agent.wait_epic_follows = [
                view
                for view in (agent.wait_epic_follows or [])
                if getattr(view, "target", None) in set(runner_follow)
            ]
        agent.wait_duration = None
        agent.wait_until = None
        if result.capacity_multiplier is not None and result.capacity is None:
            agent.set_queue_capacity(
                None,
                explicit=True,
                multiplier=result.capacity_multiplier,
            )
        else:
            agent.set_queue_capacity(
                result.capacity, explicit=result.capacity is not None
            )
        if update_wait_priority:
            agent.wait_priority = result.priority
            agent.wait_priority_explicit = result.priority is not None
        agent.status = runner_slot_display_status(
            agent.status,
            slot_queued=True,
        )
        from ._roster_generation import notify_roster_status_mutation

        notify_roster_status_mutation(self)
        label = _capacity_wait_label(result)
        if result.priority is not None:
            label = f"{label}, priority {result.priority}"
        self.notify(f"Capacity wait: {label}")  # type: ignore[attr-defined]
        self._refresh_agents_display(list_changed=False)  # type: ignore[attr-defined]


__all__ = ["AgentWaitRunnerMixin"]
