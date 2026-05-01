"""Repeat agent launch mixin (``%r:N`` directive)."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._types import PromptContext

_REPEAT_SPAWN_SLEEP = 1.0


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
            spawn_repeat_batch,
        )

        try:
            from sase.agent.launch_timing import LaunchTimingRecorder
            from sase.running_field import (
                get_first_available_axe_workspace,
                get_workspace_directory,
                get_workspace_directory_for_num,
            )
            from sase.core.time import generate_timestamp

            timer = LaunchTimingRecorder(
                "tui_agent_launch_fanout",
                {
                    "fanout_kind": "repeat",
                    "project_name": ctx.project_name,
                    "home_mode": ctx.is_home_mode,
                },
            )

            def _spawn_one(spec: RepeatAgentSpec) -> None:
                with timer.stage("timestamp_allocate", slot_index=spec.iteration):
                    timestamp = generate_timestamp()
                    workflow_name = f"ace(run)-{timestamp}"

                with timer.stage("workspace_allocation", slot_index=spec.iteration):
                    if has_wait and not ctx.is_home_mode:
                        workspace_num = 0
                        workspace_dir = get_workspace_directory(ctx.project_name, 1)
                    elif ctx.is_home_mode:
                        workspace_num = ctx.workspace_num
                        workspace_dir = ctx.workspace_dir
                    else:
                        workspace_num = get_first_available_axe_workspace(
                            ctx.project_file
                        )
                        workspace_dir, _ = get_workspace_directory_for_num(
                            workspace_num, ctx.project_name
                        )

                extra_env = {
                    REPEAT_NAME_ENV: spec.name,
                    REPEAT_ITERATION_ENV: str(spec.iteration),
                    REPEAT_TOTAL_ENV: str(spec.total),
                }

                with timer.stage("low_level_spawn", slot_index=spec.iteration):
                    self._launch_background_agent(  # type: ignore[attr-defined]
                        cl_name=ctx.display_name,
                        project_file=ctx.project_file,
                        workspace_dir=workspace_dir,
                        workspace_num=workspace_num,
                        workflow_name=workflow_name,
                        prompt=spec.prompt,
                        timestamp=timestamp,
                        update_target=ctx.update_target,
                        project_name=ctx.project_name,
                        history_sort_key=ctx.history_sort_key,
                        is_home_mode=ctx.is_home_mode,
                        vcs_ref=vcs_ref,
                        deferred_workspace=has_wait,
                        extra_env=extra_env,
                    )
                self.call_later(  # type: ignore[attr-defined]
                    self.request_agents_refresh,  # type: ignore[attr-defined]
                    "launch",
                )

            specs = spawn_repeat_batch(
                prompt,
                base_spawn_fn=_spawn_one,
                sleep_between=_REPEAT_SPAWN_SLEEP,
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
