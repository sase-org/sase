"""Multi-model agent launch mixin (``%m(...)`` directive)."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._types import PromptContext


class MultiModelLaunchMixin:
    """Mixin providing multi-model agent launch."""

    def _launch_multi_model_agents(
        self,
        model_prompts: list[str],
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
        has_wait: bool,
    ) -> None:
        """Launch one agent per model for a multi-model directive.

        Each prompt in *model_prompts* already has the multi-model directive
        (e.g. ``%m(opus,sonnet)``) replaced with a single ``%model:X``.

        Args:
            model_prompts: Per-model prompts to launch.
            ctx: The prompt context with project/workspace info.
            vcs_ref: Resolved VCS reference, if any.
            has_wait: Whether the prompt has ``%wait`` directives.
        """
        n = len(model_prompts)
        snap = dataclasses.replace(ctx)

        async def _runner() -> None:
            await asyncio.to_thread(
                self._run_multi_model_launch, model_prompts, snap, vcs_ref, has_wait
            )

        self.notify(f"Launching {n} agent(s) for {snap.display_name}...")  # type: ignore[attr-defined]
        self.call_later(_runner)  # type: ignore[attr-defined]

    def _run_multi_model_launch(
        self,
        model_prompts: list[str],
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
        has_wait: bool,
    ) -> None:
        """Worker-thread body for :meth:`_launch_multi_model_agents`."""
        try:
            from sase.agent.launch_timing import LaunchTimingRecorder
            from sase.agent.launch_executor import (
                LaunchExecutionContext,
                LaunchSpawnRequest,
                execute_launch_plan,
            )
            from sase.core.agent_launch_facade import plan_fake_fanout

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

            plan = plan_fake_fanout("model", model_prompts)
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

            timer = LaunchTimingRecorder(
                "tui_agent_launch_fanout",
                {
                    "fanout_kind": "model",
                    "slot_count": len(model_prompts),
                    "project_name": ctx.project_name,
                    "home_mode": ctx.is_home_mode,
                },
            )
            with timer.stage("execute_launch_plan", slot_count=len(model_prompts)):
                execution = execute_launch_plan(
                    plan,
                    context,
                    spawn=_spawn_from_tui,
                    on_slot_executed=_refresh_after_slot,
                )

            msg = f"Started {execution.launched_count} agent(s) for {ctx.display_name}"
            timer.finish(outcome="ok", launched=execution.launched_count)
            self.call_later(lambda: self.notify(msg))  # type: ignore[attr-defined]
        except Exception:
            log.exception("Multi-model launch failed")
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(  # type: ignore[attr-defined]
                    "Multi-model launch failed (see log)", severity="error"
                )
            )
