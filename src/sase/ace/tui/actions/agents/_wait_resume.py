"""Agent wait and fork actions for the ace TUI app."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Literal, cast

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    agent_prompt_name,
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
from ._fork_scope import (
    AgentForkScope,
    agent_fork_scope,
    clan_fork_scope,
    resolve_fork_scope_vcs_tag,
    resolve_vcs_tag,
    same_fork_scope,
    tribe_fork_scope,
)
from sase.plan_chain import agent_family_role_for_suffix

from ...models.agent_status import is_resumable_done_status

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...modals import WaitAgentCandidate, WaitModalResult

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Post-plan handoff statuses where forking should pick up the coder
# follow-up's chat rather than the planner's. Symmetric with the
# DISMISSABLE_STATUSES set used by other consumers.
_PLAN_HANDOFF_DONE_STATUSES: frozenset[str] = frozenset({"PLAN DONE", "TALE DONE"})

log = logging.getLogger(__name__)


def _is_coder_followup_suffix(suffix: str | None) -> bool:
    """Return True for the coder follow-up suffix."""
    return agent_family_role_for_suffix(suffix) == "code"


def _is_agent_family_root(agent: Agent) -> bool:
    return not agent.is_workflow_child and (
        agent.plan_chain_root or agent.agent_family_role == "root"
    )


def _agent_prompt_name(agent: Agent) -> str | None:
    """Return the name wait/fork/copy prompts should use for a row."""
    return agent_prompt_name(agent)


def _wait_spec_label(result: WaitModalResult) -> str:
    """Build a user-facing label for a wait spec."""
    if result.agents and result.time_token:
        label = f"waiting for {', '.join(result.agents)}, then {result.time_token}"
    elif result.agents:
        label = f"waiting for {', '.join(result.agents)}"
    elif result.time_token:
        label = f"waiting until {result.time_token}"
    elif result.runners is not None:
        label = f"waiting for runners ≤ {result.runners}"
    else:
        return "running now"
    if result.runners is not None and (result.agents or result.time_token):
        label = f"{label}, with runners ≤ {result.runners}"
    return label


def _result_has_wait_spec(result: WaitModalResult) -> bool:
    """Return whether the result contains a wait dependency or time floor."""
    return bool(result.agents or result.time_token or result.runners is not None)


def _prompt_wait_spec(result: WaitModalResult) -> PromptWaitDirective | None:
    """Convert a modal result to a prompt directive edit payload."""
    if not _result_has_wait_spec(result):
        return None
    return PromptWaitDirective(
        agents=tuple(result.agents),
        time_token=result.time_token,
        runners=result.runners,
    )


def _wait_candidate_from_completion(
    candidate: AgentCompletionCandidate,
) -> WaitAgentCandidate:
    """Convert a shared completion candidate to the wait modal row shape."""
    from ...modals import WaitAgentCandidate

    return WaitAgentCandidate(
        wait_name=candidate.name,
        label=candidate.label,
        status=candidate.status,
        runtime=candidate.runtime,
        model=candidate.model,
        start_time=candidate.start_time,
        duration=candidate.duration,
        role=candidate.role,
        tag=candidate.tag,
        vcs_workflow=candidate.vcs_workflow,
        prompt_snippet=candidate.prompt_snippet,
    )


def _wait_modal_candidates(
    selected_agent: Agent,
    visible_agents: list[Agent],
) -> list[WaitAgentCandidate]:
    """Return wait candidates from visible rows, excluding self and unnamed rows."""
    return [
        _wait_candidate_from_completion(candidate)
        for candidate in build_agent_completion_candidates(
            visible_agents,
            exclude_identity=selected_agent.identity,
        )
        if candidate.kind in {"agent", "family"}
    ]


def _resolve_vcs_tag(
    agent: Agent,
    name: str,
    agents: list[Agent] | None = None,
) -> str | None:
    """Resolve one agent's display-ready smart VCS launch tag."""
    return resolve_vcs_tag(agent, name, agents or ())


def _fork_panel_keys(owner: Any) -> list[str | None]:
    """Return the cached effective panel key for every loaded agent."""
    index_resolver = getattr(owner, "_agent_panel_index", None)
    if callable(index_resolver):
        try:
            keys = list(index_resolver().keys_per_agent)
            if len(keys) == len(owner._agents):
                return keys
        except Exception:
            pass
    key_resolver = getattr(owner, "_panel_keys_per_agent", None)
    if callable(key_resolver):
        try:
            keys = list(key_resolver())
            if len(keys) == len(owner._agents):
                return keys
        except Exception:
            pass

    from ...models.agent_panels import effective_tag_per_agent

    return effective_tag_per_agent(owner._agents)


def _resolve_agent_fork_scope(
    owner: Any,
) -> tuple[AgentForkScope | None, str | None]:
    """Resolve the current in-memory Agents-tab selection into a fork scope."""
    panel_resolver = getattr(owner, "_resolve_focused_panel", None)
    focus = panel_resolver() if callable(panel_resolver) else None
    if focus is not None:
        panel_key = getattr(focus, "panel_key", None)
        if not panel_key:
            return None, "The untagged panel cannot be forked"
        scope = tribe_fork_scope(panel_key, owner._agents, _fork_panel_keys(owner))
        if scope is None:
            return None, f"Tribe '@{panel_key}' has no agents"
        return scope, None

    if getattr(owner, "_current_group_key", None) is not None:
        return None, "No agent, clan, or tribe selected"

    agent = owner._get_selected_agent()
    if agent is None:
        return None, "No agent, clan, or tribe selected"

    if agent.is_clan_container:
        scope = clan_fork_scope(agent, owner._agents)
        if scope is None:
            label = agent.agent_clan or agent.display_name
            return None, f"Clan '{label}' has no agents"
        return scope, None

    from ._core import DISMISSABLE_STATUSES

    prompt_name = _agent_prompt_name(agent)
    if agent.status not in DISMISSABLE_STATUSES and prompt_name:
        return agent_fork_scope(agent, prompt_name), None

    if agent.status in _PLAN_HANDOFF_DONE_STATUSES and not _is_agent_family_root(agent):
        coder = next(
            (
                followup
                for followup in agent.followup_agents
                if _is_coder_followup_suffix(followup.role_suffix)
            ),
            None,
        )
        if coder and coder.agent_name:
            return (
                agent_fork_scope(
                    agent,
                    coder.agent_name,
                    vcs_prompt_name=coder.agent_name,
                ),
                None,
            )

    if not is_resumable_done_status(agent.status):
        return None, "Agent not finished yet"
    if not prompt_name:
        return None, "No agent name found"
    return agent_fork_scope(agent, prompt_name), None


class AgentWaitResumeMixin:
    """Mixin providing agent wait and resume actions.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]

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
        candidates = _wait_modal_candidates(
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
        if agent.slot_requested_at and not result.agents and not result.time_token:
            self._apply_live_runner_wait(artifacts_dir, agent, result)
            return
        if result.time_token or result.runners is not None or agent.slot_requested_at:
            self._apply_wait_relaunch(agent, result)
            return

        wait_names = list(result.agents)
        if wait_names:
            wait_spec = PromptWaitDirective(agents=tuple(wait_names))
            spec = AgentDirectivePersistenceSpec(
                artifacts_dir=artifacts_dir,
                prompt_mutator=lambda prompt: set_prompt_wait(prompt, wait_spec),
                meta_patch=wait_meta_patch_for_token(wait_names=tuple(wait_names)),
                waiting_marker=waiting_marker_patch_for_token(
                    wait_names=tuple(wait_names),
                ),
            )
            prior_waiting_for = list(agent.waiting_for)
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
            agent.wait_duration = None
            agent.wait_until = None
            wait_label = ", ".join(wait_names)
            self.notify(f"Now waiting for: {wait_label}")  # type: ignore[attr-defined]
            self._refresh_agents_display(list_changed=False)  # type: ignore[attr-defined]
        else:
            spec = AgentDirectivePersistenceSpec(
                artifacts_dir=artifacts_dir,
                prompt_mutator=lambda prompt: set_prompt_wait(prompt, None),
                meta_patch=wait_meta_patch_for_token(),
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

            task_info = self._submit_tracked_task(  # type: ignore[attr-defined]
                "agent-directive",
                agent.cl_name or agent.display_name or "agent",
                artifacts_dir,
                _task,
                display_name=f"Persist run-now: {agent.display_name}",
                dedup_key=f"agent-directive-persist:{artifacts_dir}",
                duplicate_message="A directive update is already running for this agent",
                on_complete=_on_complete,
                reload_on_complete=False,
                notify_on_complete=False,
            )
            if task_info is None:
                return
            agent.waiting_for = []
            agent.wait_duration = None
            agent.wait_until = None
            self.notify(f"Wait: {agent.display_name or agent.cl_name}")  # type: ignore[attr-defined]
            self._refresh_agents_display(list_changed=False)  # type: ignore[attr-defined]

    def _apply_live_runner_wait(
        self,
        artifacts_dir: str,
        agent: Agent,
        result: WaitModalResult,
    ) -> None:
        """Update a parked slot wait in place for the next runner poll."""
        wait_spec = _prompt_wait_spec(result)
        spec = AgentDirectivePersistenceSpec(
            artifacts_dir=artifacts_dir,
            prompt_mutator=lambda prompt: set_prompt_wait(prompt, wait_spec),
            meta_patch=wait_meta_patch_for_token(
                update_wait_runners=True,
                wait_runners=result.runners,
            ),
            waiting_marker=waiting_marker_patch_for_token(
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
        if result.run_now or not _result_has_wait_spec(result):
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
        # Get the raw prompt before killing
        raw_content = agent.get_raw_xprompt_content()
        if not raw_content:
            self.notify("No prompt found for agent", severity="warning")  # type: ignore[attr-defined]
            return

        from ...modals import ConfirmKillModal

        desc_parts = [f"Kill and restart {_wait_spec_label(result)}"]
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

            # Kill the agent
            self._do_kill_agent(agent)  # type: ignore[attr-defined]

            wait_spec = _prompt_wait_spec(result)
            if wait_spec is None:
                return
            new_prompt = set_prompt_wait(raw_content, wait_spec)

            self._setup_home_prompt_context(  # type: ignore[attr-defined]
                display_name=agent.display_name or agent.cl_name,
                history_sort_key=agent.cl_name or "wait",
            )
            self._finish_agent_launch(new_prompt)  # type: ignore[attr-defined]

        self.push_screen(ConfirmKillModal(agent_description), on_confirm)  # type: ignore[attr-defined]

    def action_fork_agent(self) -> None:
        """Fork the selected agent, clan, or named tribe."""
        if self.current_tab != "agents":
            return

        scope, warning = _resolve_agent_fork_scope(self)
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
        current_scope, _warning = _resolve_agent_fork_scope(self)
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
        name = _agent_prompt_name(agent)
        if not name:
            self.notify("No agent name found", severity="warning")  # type: ignore[attr-defined]
            return

        prefix = f"%w:{name} "

        vcs_tag = _resolve_vcs_tag(agent, name, self._agents)
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
        named: list[Agent] = [a for a in marked if _agent_prompt_name(a)]
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

        names = [_agent_prompt_name(a) for a in named]
        prefix = f"%w:{','.join(n for n in names if n)} "

        cursor = self._get_selected_agent()  # type: ignore[attr-defined]
        tag_source = cursor if cursor is not None and cursor in named else named[0]
        tag_source_name = _agent_prompt_name(tag_source)
        assert tag_source_name is not None
        vcs_tag = _resolve_vcs_tag(tag_source, tag_source_name, self._agents)
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
