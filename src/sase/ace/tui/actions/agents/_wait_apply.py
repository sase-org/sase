"""Wait persistence actions for waiting and queued agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.project_display_names import humanize_cl_name
from sase.macro.directive_edit import PromptWaitDirective

from ..proc_actions import TrackedProcCompletion

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import WaitModalResult


class AgentWaitApplyMixin:
    """Mixin persisting wait edits for waiting and queued agents."""

    def _apply_wait(
        self,
        artifacts_dir: str,
        agent: Agent,
        result: WaitModalResult,
    ) -> None:
        """Apply a WAITING- or QUEUED-agent wait result."""
        if result.run_now and agent.slot_requested_at:
            self._apply_live_runner_wait(artifacts_dir, agent, result)  # type: ignore[attr-defined]
            return
        if (
            not result.run_now
            and agent.slot_requested_at
            and not result.agents
            and not result.hoods
            and not result.time_token
        ):
            self._apply_live_runner_wait(artifacts_dir, agent, result)  # type: ignore[attr-defined]
            return
        if not result.run_now and (
            result.time_token
            or result.capacity is not None
            or result.capacity_multiplier is not None
            or agent.slot_requested_at
        ):
            self._apply_wait_relaunch(agent, result)  # type: ignore[attr-defined]
            return

        from ._wait_helpers import authored_result_beads

        wait_names = list(result.agents)
        wait_beads = list(authored_result_beads(result, agent))
        wait_hoods = list(result.hoods)
        if wait_names or wait_beads or wait_hoods or result.priority is not None:
            update_wait_priority = result.priority is not None or result.update_priority
            effective_priority = (
                result.priority
                if update_wait_priority
                else agent.wait_priority
                if agent.wait_priority_explicit
                else None
            )
            if result.epic_follow_agents is not None:
                follow_names = [n for n in result.epic_follow_agents if n in wait_names]
            else:
                current_follow = list(getattr(agent, "wait_for_epics_of", None) or [])
                follow_names = [n for n in current_follow if n in wait_names]
            wait_spec = PromptWaitDirective(
                agents=tuple(wait_names),
                priority=effective_priority,
                beads=tuple(wait_beads),
                hoods=tuple(wait_hoods),
                epic_follow_agents=(
                    # Preserve an explicit modal choice, including off (no
                    # follow): under the flipped default only an explicit
                    # for_epic=false keeps the wait agent-only.
                    tuple(follow_names)
                    if result.epic_follow_agents is not None
                    else (tuple(follow_names) or None)
                ),
            )
            prior_waiting_for = list(agent.waiting_for)
            prior_waiting_for_beads = list(agent.waiting_for_beads)
            prior_waiting_for_hoods = list(agent.waiting_for_hoods)
            prior_wait_for_epics_of = list(
                getattr(agent, "wait_for_epics_of", None) or []
            )
            prior_wait_epic_follows = list(
                getattr(agent, "wait_epic_follows", None) or []
            )
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
                try:
                    from ._roster_generation import notify_roster_status_mutation

                    notify_roster_status_mutation(self)
                except Exception:  # noqa: BLE001 - cache invalidation only.
                    pass
                self.notify(  # type: ignore[attr-defined]
                    f"Wait persist failed: {completion.message}",
                    severity="error",
                )
                refresh = getattr(self, "_schedule_agents_async_refresh", None)
                if callable(refresh):
                    refresh(source="agent-wait-persist-failed")

            submitted = submit_agent_directive(
                self,
                artifacts_dir=artifacts_dir,
                payload={
                    "prompt": {
                        "kind": "set_wait",
                        "wait": {
                            "agents": list(wait_spec.agents),
                            "beads": list(wait_spec.beads),
                            "hoods": list(wait_spec.hoods),
                            "priority": wait_spec.priority,
                            "epic_follow_agents": (
                                list(wait_spec.epic_follow_agents)
                                if wait_spec.epic_follow_agents is not None
                                else None
                            ),
                        },
                    },
                    "wait": {
                        "beads": wait_beads,
                        "hoods": wait_hoods,
                        "names": wait_names,
                        "wait_for_epics_of": list(follow_names),
                        "update_wait_priority": update_wait_priority,
                        "wait_priority": result.priority,
                    },
                    "waiting": {
                        "beads": wait_beads,
                        "hoods": wait_hoods,
                        "names": wait_names,
                        "wait_for_epics_of": list(follow_names),
                        "update_wait_priority": update_wait_priority,
                        "wait_priority": result.priority,
                    },
                },
                cl_name=agent.cl_name or agent.display_name or "agent",
                display_name=f"Persist wait: {agent.display_name}",
                on_complete=_on_complete,
            )
            if not submitted:
                return
            agent.waiting_for = wait_names
            agent.waiting_for_beads = wait_beads
            agent.waiting_for_hoods = wait_hoods
            if hasattr(agent, "wait_for_epics_of"):
                agent.wait_for_epics_of = list(follow_names)
            if hasattr(agent, "wait_epic_follows"):
                agent.wait_epic_follows = [
                    view
                    for view in (agent.wait_epic_follows or [])
                    if getattr(view, "target", None) in set(follow_names)
                ]
            agent.wait_duration = None
            agent.wait_until = None
            if update_wait_priority:
                agent.wait_priority = result.priority
                agent.wait_priority_explicit = result.priority is not None
            try:
                from ._roster_generation import notify_roster_status_mutation

                notify_roster_status_mutation(self)
            except Exception:  # noqa: BLE001 - cache invalidation only.
                pass
            wait_label_parts = [", ".join(wait_names)] if wait_names else []
            if wait_beads:
                wait_label_parts.append("beads: " + ", ".join(wait_beads))
            if wait_hoods:
                wait_label_parts.append("hoods: " + ", ".join(wait_hoods))
            if result.priority is not None:
                wait_label_parts.append(f"priority: {result.priority}")
            wait_label = "; ".join(wait_label_parts)
            self.notify(f"Now waiting for: {wait_label}")  # type: ignore[attr-defined]
            self._refresh_agents_display(list_changed=False)  # type: ignore[attr-defined]
        else:
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
                self.notify(  # type: ignore[attr-defined]
                    f"Run-now persist failed: {completion.message}",
                    severity="error",
                )
                refresh = getattr(self, "_schedule_agents_async_refresh", None)
                if callable(refresh):
                    refresh(source="agent-run-now-persist-failed")

            display_name = humanize_cl_name(
                agent.display_name or agent.cl_name or "agent"
            )
            submitted = submit_agent_directive(
                self,
                artifacts_dir=artifacts_dir,
                payload={
                    "prompt": {"kind": "set_wait", "wait": None},
                    "ready": {
                        "resolved_deps": list(agent.waiting_for),
                        "unwait": True,
                    },
                    "wait": {
                        "update_wait_priority": True,
                        "update_wait_runners": True,
                    },
                },
                cl_name=agent.cl_name or agent.display_name or "agent",
                display_name=f"Persist run-now: {display_name}",
                on_complete=_on_complete,
            )
            if not submitted:
                return
            agent.waiting_for = []
            agent.waiting_for_beads = []
            agent.waiting_for_hoods = []
            if hasattr(agent, "wait_for_epics_of"):
                agent.wait_for_epics_of = []
            if hasattr(agent, "wait_epic_follows"):
                agent.wait_epic_follows = []
            agent.wait_duration = None
            agent.wait_until = None
            agent.set_queue_capacity(None, explicit=False)
            agent.wait_priority = None
            agent.wait_priority_explicit = False
            agent.slot_requested_at = None
            try:
                from ._roster_generation import notify_roster_status_mutation

                notify_roster_status_mutation(self)
            except Exception:  # noqa: BLE001 - cache invalidation only.
                pass
            self.notify(f"Wait: {display_name}")  # type: ignore[attr-defined]
            self._refresh_agents_display(list_changed=False)  # type: ignore[attr-defined]


__all__ = ["AgentWaitApplyMixin"]
