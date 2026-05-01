"""Repeat agent launch mixin (``%r:N`` directive)."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

if TYPE_CHECKING:
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
        The ``%r`` / ``%n`` tokens are stripped from the per-agent prompt
        by :func:`spawn_repeat_batch` and each spec re-injects ``%n:<name>``
        so the runner assigns the per-slot name correctly.

        Args:
            prompt: Raw prompt containing ``%r:N`` (optionally with ``%n``).
            ctx: The prompt context with project/workspace info.
            vcs_ref: Resolved VCS reference, if any.
            has_wait: Whether the prompt has ``%wait`` directives.
        """
        snap = dataclasses.replace(ctx)

        async def _runner() -> None:
            await asyncio.to_thread(
                self._run_repeat_launch, prompt, snap, vcs_ref, has_wait
            )

        self.notify(f"Launching repeat agents for {snap.display_name}...")  # type: ignore[attr-defined]
        self.call_later(_runner)  # type: ignore[attr-defined]

    def _run_repeat_launch(
        self,
        prompt: str,
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
        has_wait: bool,
    ) -> None:
        """Worker-thread body for :meth:`_launch_repeat_agents`."""
        from sase.agent.repeat_launcher import (
            NameCollisionError,
            REPEAT_ITERATION_ENV,
            REPEAT_NAME_ENV,
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
                allocate_launch_timestamp_batch,
                plan_fake_fanout,
            )
            from sase.core.agent_launch_wire import LaunchFanoutSlotWire

            timer = LaunchTimingRecorder(
                "tui_agent_launch_fanout",
                {
                    "fanout_kind": "repeat",
                    "project_name": ctx.project_name,
                    "home_mode": ctx.is_home_mode,
                },
            )
            repeat_count, _, _ = extract_repeat_and_name(prompt)
            timestamps = (
                allocate_launch_timestamp_batch(repeat_count)
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
                return {
                    REPEAT_NAME_ENV: spec.name,
                    REPEAT_ITERATION_ENV: str(spec.iteration),
                    REPEAT_TOTAL_ENV: str(spec.total),
                }

            def _spawn_from_tui(request: LaunchSpawnRequest) -> None:
                self._launch_background_agent(  # type: ignore[attr-defined]
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
                )

            def _refresh_after_slot(_record: object) -> None:
                self.call_later(  # type: ignore[attr-defined]
                    self.request_agents_refresh,  # type: ignore[attr-defined]
                    "launch",
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
                execute_launch_plan(
                    plan,
                    context,
                    spawn=_spawn_from_tui,
                    on_slot_executed=_refresh_after_slot,
                    slot_extra_env=_slot_env,
                )

            msg = f"Started {len(specs)} repeat agent(s) for {ctx.display_name}"
            timer.finish(outcome="ok", launched=len(specs))
            self.call_later(lambda: self.notify(msg))  # type: ignore[attr-defined]
        except NameCollisionError as e:
            err_msg = str(e)
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(err_msg, severity="error")  # type: ignore[attr-defined]
            )
        except Exception:
            log.exception("Repeat launch failed")
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(  # type: ignore[attr-defined]
                    "Repeat launch failed (see log)", severity="error"
                )
            )
