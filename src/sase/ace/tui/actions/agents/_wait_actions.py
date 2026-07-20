"""Wait editing and persistence actions for agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    build_agent_completion_candidates,
    visible_agent_completion_agents,
)
from sase.project_display_names import humanize_cl_name
from sase.xprompt.directive_edit import PromptWaitDirective, set_prompt_wait

from ..task_actions import TrackedTaskCompletion, TrackedTaskResult
from ._directive_persistence import (
    AgentDirectivePersistenceResult,
    AgentDirectivePersistenceSpec,
    ReadyMarkerPatch,
    persist_agent_directive_update,
    wait_meta_patch_for_token,
    waiting_marker_patch_for_token,
)
from ._wait_helpers import (
    TabName,
    prompt_wait_spec,
    result_has_wait_spec,
    wait_modal_candidates,
    wait_spec_label,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import WaitModalResult


class AgentWaitActionsMixin:
    """Mixin providing agent wait editing and persistence actions."""

    current_tab: TabName

    def action_reword(self) -> None:
        """Reword or wait - behavior depends on current tab."""
        if self.current_tab == "agents":
            self._wait_agent()
        else:
            # Call parent implementation for ChangeSpecs
            super().action_reword()  # type: ignore[misc]

    def _wait_agent(self) -> None:
        """Prompt for an agent name to wait for, or run immediately."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.status not in ("STARTING", "WAITING", "RUNNING"):
            self.notify(  # type: ignore[attr-defined]
                "Agent is not starting, waiting, or running",
                severity="warning",
            )
            return

        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if not artifacts_dir:
            self.notify("No artifacts directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        from ...modals import WaitModal, WaitModalResult

        is_running = agent.status in {"STARTING", "RUNNING"}
        candidates = wait_modal_candidates(
            agent,
            self._visible_agent_completion_agents(),
        )

        def handle_wait_result(result: WaitModalResult | None) -> None:
            if result is None:
                return  # cancelled
            if is_running:
                self._apply_wait_running(agent, result)
            else:
                self._apply_wait(artifacts_dir, agent, result)

        self.push_screen(  # type: ignore[attr-defined]
            WaitModal(
                current_waiting_for=agent.waiting_for,
                current_waiting_for_beads=agent.waiting_for_beads,
                current_wait_duration=agent.wait_duration,
                current_wait_until=agent.wait_until,
                current_wait_runners=(
                    agent.wait_runners if agent.wait_runners_explicit else None
                ),
                candidates=candidates,
                is_running=is_running,
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
        return build_agent_completion_candidates(
            self._visible_agent_completion_agents(),
            exclude_identity=exclude_identity,
        )

    def _apply_wait(
        self,
        artifacts_dir: str,
        agent: Agent,
        result: WaitModalResult,
    ) -> None:
        """Apply a WAITING-agent wait result."""
        if (
            not result.run_now
            and agent.slot_requested_at
            and not result.agents
            and not result.time_token
        ):
            self._apply_live_runner_wait(artifacts_dir, agent, result)
            return
        if not result.run_now and (
            result.time_token or result.runners is not None or agent.slot_requested_at
        ):
            self._apply_wait_relaunch(agent, result)
            return

        wait_names = list(result.agents)
        wait_beads = list(result.beads)
        if wait_names or wait_beads:
            wait_spec = PromptWaitDirective(
                agents=tuple(wait_names),
                beads=tuple(wait_beads),
            )
            spec = AgentDirectivePersistenceSpec(
                artifacts_dir=artifacts_dir,
                prompt_mutator=lambda prompt: set_prompt_wait(prompt, wait_spec),
                meta_patch=wait_meta_patch_for_token(
                    wait_names=tuple(wait_names),
                    wait_beads=tuple(wait_beads),
                ),
                waiting_marker=waiting_marker_patch_for_token(
                    wait_names=tuple(wait_names),
                    wait_beads=tuple(wait_beads),
                ),
            )
            prior_waiting_for = list(agent.waiting_for)
            prior_waiting_for_beads = list(agent.waiting_for_beads)
            prior_wait_duration = agent.wait_duration
            prior_wait_until = agent.wait_until

            def _task() -> TrackedTaskResult[AgentDirectivePersistenceResult]:
                payload = persist_agent_directive_update(spec)
                return TrackedTaskResult(
                    success=True,
                    message="Wait persisted",
                    payload=payload,
                )

            def _on_complete(
                completion: TrackedTaskCompletion[AgentDirectivePersistenceResult],
            ) -> None:
                if completion.success:
                    return
                agent.waiting_for = prior_waiting_for
                agent.waiting_for_beads = prior_waiting_for_beads
                agent.wait_duration = prior_wait_duration
                agent.wait_until = prior_wait_until
                self.notify(  # type: ignore[attr-defined]
                    f"Wait persist failed: {completion.message}",
                    severity="error",
                )
                refresh = getattr(self, "_schedule_agents_async_refresh", None)
                if callable(refresh):
                    refresh(source="agent-wait-persist-failed")

            task_info = self._submit_tracked_task(  # type: ignore[attr-defined]
                "agent-directive",
                agent.cl_name or agent.display_name or "agent",
                artifacts_dir,
                _task,
                display_name=f"Persist wait: {agent.display_name}",
                dedup_key=f"agent-directive-persist:{artifacts_dir}",
                duplicate_message="A directive update is already running for this agent",
                on_complete=_on_complete,
                reload_on_complete=False,
                notify_on_complete=False,
            )
            if task_info is None:
                return
            agent.waiting_for = wait_names
            agent.waiting_for_beads = wait_beads
            agent.wait_duration = None
            agent.wait_until = None
            wait_label_parts = [", ".join(wait_names)] if wait_names else []
            if wait_beads:
                wait_label_parts.append("beads: " + ", ".join(wait_beads))
            wait_label = "; ".join(wait_label_parts)
            self.notify(f"Now waiting for: {wait_label}")  # type: ignore[attr-defined]
            self._refresh_agents_display(list_changed=False)  # type: ignore[attr-defined]
        else:
            spec = AgentDirectivePersistenceSpec(
                artifacts_dir=artifacts_dir,
                prompt_mutator=lambda prompt: set_prompt_wait(prompt, None),
                meta_patch=wait_meta_patch_for_token(update_wait_runners=True),
                ready_marker=ReadyMarkerPatch(
                    resolved_deps=tuple(agent.waiting_for),
                    unwait=True,
                ),
            )

            def _task() -> TrackedTaskResult[AgentDirectivePersistenceResult]:
                payload = persist_agent_directive_update(spec)
                return TrackedTaskResult(
                    success=True,
                    message="Run-now persisted",
                    payload=payload,
                )

            def _on_complete(
                completion: TrackedTaskCompletion[AgentDirectivePersistenceResult],
            ) -> None:
                if completion.success:
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
            task_info = self._submit_tracked_task(  # type: ignore[attr-defined]
                "agent-directive",
                agent.cl_name or agent.display_name or "agent",
                artifacts_dir,
                _task,
                display_name=f"Persist run-now: {display_name}",
                dedup_key=f"agent-directive-persist:{artifacts_dir}",
                duplicate_message="A directive update is already running for this agent",
                on_complete=_on_complete,
                reload_on_complete=False,
                notify_on_complete=False,
            )
            if task_info is None:
                return
            agent.waiting_for = []
            agent.waiting_for_beads = []
            agent.wait_duration = None
            agent.wait_until = None
            agent.wait_runners = None
            agent.wait_runners_explicit = False
            agent.slot_requested_at = None
            self.notify(f"Wait: {display_name}")  # type: ignore[attr-defined]
            self._refresh_agents_display(list_changed=False)  # type: ignore[attr-defined]

    def _apply_live_runner_wait(
        self,
        artifacts_dir: str,
        agent: Agent,
        result: WaitModalResult,
    ) -> None:
        """Update a parked slot wait in place for the next runner poll."""
        wait_spec = prompt_wait_spec(result)
        spec = AgentDirectivePersistenceSpec(
            artifacts_dir=artifacts_dir,
            prompt_mutator=lambda prompt: set_prompt_wait(prompt, wait_spec),
            meta_patch=wait_meta_patch_for_token(
                wait_beads=tuple(result.beads),
                update_wait_runners=True,
                wait_runners=result.runners,
            ),
            waiting_marker=waiting_marker_patch_for_token(
                wait_beads=tuple(result.beads),
                update_wait_runners=True,
                wait_runners=result.runners,
            ),
        )
        prior_runners = agent.wait_runners
        prior_explicit = agent.wait_runners_explicit

        def _task() -> TrackedTaskResult[AgentDirectivePersistenceResult]:
            payload = persist_agent_directive_update(spec)
            return TrackedTaskResult(
                success=True,
                message="Runner wait persisted",
                payload=payload,
            )

        def _on_complete(
            completion: TrackedTaskCompletion[AgentDirectivePersistenceResult],
        ) -> None:
            if completion.success:
                return
            agent.wait_runners = prior_runners
            agent.wait_runners_explicit = prior_explicit
            self.notify(  # type: ignore[attr-defined]
                f"Runner wait persist failed: {completion.message}",
                severity="error",
            )
            refresh = getattr(self, "_schedule_agents_async_refresh", None)
            if callable(refresh):
                refresh(source="agent-runner-wait-persist-failed")

        task_info = self._submit_tracked_task(  # type: ignore[attr-defined]
            "agent-directive",
            agent.cl_name or agent.display_name or "agent",
            artifacts_dir,
            _task,
            display_name=f"Persist runner wait: {agent.display_name}",
            dedup_key=f"agent-directive-persist:{artifacts_dir}",
            duplicate_message="A directive update is already running for this agent",
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        if task_info is None:
            return
        if result.runners is not None:
            agent.wait_runners = result.runners
        agent.wait_runners_explicit = result.runners is not None
        label = (
            f"runners ≤ {result.runners}"
            if result.runners is not None
            else "global runner cap"
        )
        self.notify(f"Runner wait: {label}")  # type: ignore[attr-defined]
        self._refresh_agents_display(list_changed=False)  # type: ignore[attr-defined]

    def _apply_wait_running(self, agent: Agent, result: WaitModalResult) -> None:
        """Kill an active agent and restart with a canonical wait directive."""
        if result.run_now or not result_has_wait_spec(result):
            status = (agent.status or "active").lower()
            self.notify(f"Agent is already {status}", severity="warning")  # type: ignore[attr-defined]
            return
        self._apply_wait_relaunch(agent, result)

    def _apply_wait_relaunch(
        self,
        agent: Agent,
        result: WaitModalResult,
    ) -> None:
        """Confirm-kill and relaunch an agent with a replacement wait directive."""
        raw_content = agent.get_raw_xprompt_content()
        if not raw_content:
            self.notify("No prompt found for agent", severity="warning")  # type: ignore[attr-defined]
            return

        from ...modals import ConfirmKillModal

        desc_parts = [f"Kill and restart {wait_spec_label(result)}"]
        if agent.cl_name:
            desc_parts.append(
                f"ChangeSpec: {agent.display_name or humanize_cl_name(agent.cl_name)}"
            )
        if agent.pid:
            desc_parts.append(f"PID: {agent.pid}")
        agent_description = "\n".join(desc_parts)

        def on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return

            self._do_kill_agent(agent)  # type: ignore[attr-defined]

            wait_spec = prompt_wait_spec(result)
            if wait_spec is None:
                return
            new_prompt = set_prompt_wait(raw_content, wait_spec)

            self._setup_home_prompt_context(  # type: ignore[attr-defined]
                display_name=agent.display_name or agent.cl_name,
                history_sort_key=agent.cl_name or "wait",
            )
            self._finish_agent_launch(new_prompt)  # type: ignore[attr-defined]

        self.push_screen(ConfirmKillModal(agent_description), on_confirm)  # type: ignore[attr-defined]
