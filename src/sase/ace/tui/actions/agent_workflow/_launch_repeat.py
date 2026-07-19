"""Repeat agent launch mixin (``%r:N`` directive)."""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

from ._launch_tasks import LaunchTaskOutcome, launch_results_tuple
from ..failure_messages import with_log_panel_hint

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult

    from ._types import PromptContext


_REPEAT_SPAWN_SLEEP = 0.0


class RepeatLaunchMixin:
    """Mixin providing repeat agent launch."""

    def _launch_repeat_agents(
        self,
        prompt: str,
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
        has_wait: bool,
    ) -> None:
        """Launch one independent agent per ``%r:N`` iteration.

        Each iteration becomes its own top-level subprocess with name
        ``<base>.<k>``, its own workspace, and its own ``agent_meta.json``.
        The ``%r`` / ``%i`` tokens are stripped from the per-agent prompt
        by :func:`spawn_repeat_batch` and each spec re-injects ``%i:<name>``
        so the runner assigns the per-slot name correctly.

        Args:
            prompt: Raw prompt containing ``%r:N`` (optionally with ``%i``).
            ctx: The prompt context with project/workspace info.
            vcs_ref: Resolved VCS reference, if any.
            has_wait: Whether the prompt has ``%wait`` directives.
        """
        snap = dataclasses.replace(ctx)

        self.notify(f"Launching repeat agents for {snap.display_name}...")  # type: ignore[attr-defined]
        self._submit_launch_task(  # type: ignore[attr-defined]
            display_name=f"launch repeat {snap.display_name}",
            cl_name=snap.display_name,
            project_file=snap.project_file,
            task_callable=lambda: self._run_repeat_launch(
                prompt, snap, vcs_ref, has_wait
            ),
            submitted_prompt=prompt,
        )

    def _run_repeat_launch(
        self,
        prompt: str,
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
        has_wait: bool,
    ) -> LaunchTaskOutcome:
        """Worker-thread body for :meth:`_launch_repeat_agents`."""
        from sase.agent.repeat_launcher import (
            NameCollisionError,
            REPEAT_ITERATION_ENV,
            REPEAT_NAME_ENV,
            REPEAT_PREV_NAME_ENV,
            REPEAT_TOTAL_ENV,
            RepeatAgentSpec,
            extract_repeat_and_name,
            spawn_repeat_batch,
        )

        try:
            from sase.agent.launch_timing import LaunchTimingRecorder
            from sase.agent.launch_executor import (
                LaunchExecutionContext,
                LaunchSpawnRequest,
                execute_launch_plan,
            )
            from sase.core.agent_launch_facade import (
                plan_fake_fanout,
                reserve_launch_timestamp_batch,
            )
            from sase.core.agent_launch_wire import LaunchFanoutSlotWire

            timer = LaunchTimingRecorder(
                "tui_agent_launch_fanout",
                {
                    "fanout_kind": "repeat",
                    "project_name": ctx.project_name,
                    "home_mode": ctx.is_home_mode,
                },
                durable=True,
            )
            repeat_count, _, _ = extract_repeat_and_name(prompt)
            timestamps = (
                reserve_launch_timestamp_batch(repeat_count)
                if repeat_count is not None
                else None
            )
            specs: list[RepeatAgentSpec] = []

            specs = spawn_repeat_batch(
                prompt,
                base_spawn_fn=specs.append,
                timestamps=timestamps,
            )
            plan = plan_fake_fanout("repeat", [spec.prompt for spec in specs])
            plan = dataclasses.replace(
                plan,
                slots=[
                    dataclasses.replace(
                        slot,
                        timestamp=spec.timestamp,
                        workflow_name=(
                            None
                            if spec.timestamp is None
                            else f"ace(run)-{spec.timestamp}"
                        ),
                        repeat_name=spec.name,
                    )
                    for slot, spec in zip(plan.slots, specs, strict=True)
                ],
            )
            specs_by_slot = dict(enumerate(specs))

            def _slot_env(slot: LaunchFanoutSlotWire) -> dict[str, str]:
                spec = specs_by_slot[slot.slot_index]
                env = {
                    REPEAT_NAME_ENV: spec.name,
                    REPEAT_ITERATION_ENV: str(spec.iteration),
                    REPEAT_TOTAL_ENV: str(spec.total),
                }
                if spec.prev_name is not None:
                    env[REPEAT_PREV_NAME_ENV] = spec.prev_name
                return env

            def _spawn_from_tui(request: LaunchSpawnRequest) -> AgentLaunchResult:
                return self._launch_background_agent(  # type: ignore[attr-defined]
                    cl_name=request.cl_name,
                    project_file=request.project_file,
                    workspace_dir=request.workspace_dir,
                    workspace_num=request.workspace_num,
                    workflow_name=request.workflow_name,
                    prompt=request.prompt,
                    timestamp=request.timestamp,
                    update_target=request.update_target,
                    project_name=request.project_name,
                    history_sort_key=request.history_sort_key,
                    is_home_mode=request.is_home_mode,
                    vcs_ref=request.vcs_ref,
                    deferred_workspace=request.deferred_workspace,
                    extra_env=request.extra_env,
                    retry_transfer_from_pid=request.transfer_from_pid,
                )

            context = LaunchExecutionContext(
                cl_name=ctx.display_name,
                project_file=ctx.project_file,
                project_name=ctx.project_name,
                update_target=ctx.update_target,
                history_sort_key=ctx.history_sort_key,
                is_home_mode=ctx.is_home_mode,
                vcs_ref=vcs_ref,
                deferred_workspace=has_wait,
                workspace_num=ctx.workspace_num,
                workspace_dir=ctx.workspace_dir,
            )
            with timer.stage("execute_launch_plan", slot_count=len(specs)):
                execution = execute_launch_plan(
                    plan,
                    context,
                    spawn=_spawn_from_tui,
                    slot_extra_env=_slot_env,
                )

            msg = f"Started {len(specs)} repeat agent(s) for {ctx.display_name}"
            timer.finish(outcome="ok", launched=len(specs))
            return LaunchTaskOutcome(
                msg,
                results=launch_results_tuple(execution.results),
            )
        except NameCollisionError as e:
            from sase.history.prompt import record_failed_launch_prompt

            record_failed_launch_prompt(prompt)
            _log_repeat_failure(e, ctx, prompt, name_collision=True)
            # A mid-plan failure may have already spawned some slots;
            # without results, only a refresh makes them visible.
            return LaunchTaskOutcome(
                with_log_panel_hint(str(e)),
                severity="error",
                request_agents_refresh=True,
            )
        except Exception as exc:
            from sase.history.prompt import record_failed_launch_prompt

            record_failed_launch_prompt(prompt)
            log.exception("Repeat launch failed")
            _log_repeat_failure(exc, ctx, prompt)
            return LaunchTaskOutcome(
                with_log_panel_hint("Repeat launch failed"),
                severity="error",
                request_agents_refresh=True,
            )


def _log_repeat_failure(
    exc: BaseException,
    ctx: PromptContext,
    prompt: str,
    *,
    name_collision: bool = False,
) -> None:
    """Durably record a repeat (``%r:N``) launch failure to the launch-failure log."""
    from sase.logs import log_launch_failure

    log_launch_failure(
        kind="repeat",
        display_name=ctx.display_name,
        exc=exc,
        project=ctx.project_name,
        workspace_num=ctx.workspace_num,
        prompt_preview=prompt,
        name_collision=name_collision,
        home_mode=ctx.is_home_mode,
    )
