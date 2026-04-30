"""Multi-prompt agent launch mixin."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._types import PromptContext


class MultiPromptLaunchMixin:
    """Mixin providing multi-prompt agent launch."""

    def _launch_multi_prompt_agents(
        self,
        multi: object,
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
    ) -> None:
        """Launch each multi-prompt segment as a separate agent.

        Snapshots the launch context on the UI thread and dispatches the
        per-segment fan-out to ``asyncio.to_thread`` so the Textual event
        loop stays responsive during naming-wait polls. Per-agent refresh
        triggers funnel through ``request_agents_refresh("launch")`` and
        collapse into a single deferred refresh after the burst settles.
        """
        from sase.agent.multi_prompt import MultiPrompt

        assert isinstance(multi, MultiPrompt)

        # Snapshot context on the UI thread so subsequent edits to
        # ``self._prompt_context`` do not leak into the worker.
        snap = dataclasses.replace(ctx)

        async def _runner() -> None:
            await asyncio.to_thread(self._run_multi_prompt_launch, multi, snap, vcs_ref)

        # Immediate feedback while agents launch in background.
        n = len(multi.segments)
        self.request_agents_refresh("launch")  # type: ignore[attr-defined]
        self.notify(f"Launching {n} agent(s) for {snap.display_name}...")  # type: ignore[attr-defined]

        self.call_later(_runner)  # type: ignore[attr-defined]

    def _run_multi_prompt_launch(
        self,
        multi: object,
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
    ) -> None:
        """Worker-thread body for :meth:`_launch_multi_prompt_agents`."""
        from sase.agent.multi_prompt import MultiPrompt
        from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

        assert isinstance(multi, MultiPrompt)

        try:
            results = launch_multi_prompt_agents(
                segments=multi.segments,
                local_xprompts=multi.local_xprompts,
                cl_name=ctx.display_name,
                project_file=ctx.project_file,
                project_name=ctx.project_name,
                is_home_mode=ctx.is_home_mode,
                vcs_ref=vcs_ref,
                on_agent_spawned=lambda: self.call_later(  # type: ignore[attr-defined]
                    self.request_agents_refresh,  # type: ignore[attr-defined]
                    "launch",
                ),
                default_bare_segments_to_home=ctx.is_home_mode,
            )
            self.call_later(self.request_agents_refresh, "launch")  # type: ignore[attr-defined]
            msg = f"Started {len(results)} agent(s) for {ctx.display_name}"
            self.call_later(lambda: self.notify(msg))  # type: ignore[attr-defined]
        except Exception:
            log.exception("Multi-prompt launch failed")
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(  # type: ignore[attr-defined]
                    "Multi-prompt launch failed (see log)", severity="error"
                )
            )
