"""Multi-model agent launch mixin (``%m(...)`` directive)."""

from __future__ import annotations

import logging
import threading
import time
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

        def _run() -> None:
            try:
                from sase.running_field import (
                    get_first_available_axe_workspace,
                    get_workspace_directory,
                    get_workspace_directory_for_num,
                )
                from sase.core.time import generate_timestamp

                launched = 0
                for i, model_prompt in enumerate(model_prompts):
                    if i > 0:
                        time.sleep(1)

                    timestamp = generate_timestamp()
                    workflow_name = f"ace(run)-{timestamp}"

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

                    self._launch_background_agent(  # type: ignore[attr-defined]
                        cl_name=ctx.display_name,
                        project_file=ctx.project_file,
                        workspace_dir=workspace_dir,
                        workspace_num=workspace_num,
                        workflow_name=workflow_name,
                        prompt=model_prompt,
                        timestamp=timestamp,
                        update_target=ctx.update_target,
                        project_name=ctx.project_name,
                        history_sort_key=ctx.history_sort_key,
                        is_home_mode=ctx.is_home_mode,
                        vcs_ref=vcs_ref,
                        deferred_workspace=has_wait,
                    )
                    launched += 1

                self.call_later(self._schedule_agents_async_refresh)  # type: ignore[attr-defined]
                msg = f"Started {launched} agent(s) for {ctx.display_name}"
                self.call_later(lambda: self.notify(msg))  # type: ignore[attr-defined]
            except Exception:
                log.exception("Multi-model launch failed")
                self.call_later(  # type: ignore[attr-defined]
                    lambda: self.notify(  # type: ignore[attr-defined]
                        "Multi-model launch failed (see log)", severity="error"
                    )
                )

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        self.notify(f"Launching {n} agent(s) for {ctx.display_name}...")  # type: ignore[attr-defined]
