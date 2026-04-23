"""Multi-prompt agent launch mixin."""

from __future__ import annotations

import logging
import threading
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

        Delegates to ``launch_multi_prompt_agents()`` in a background thread
        to avoid blocking the TUI event loop during naming-wait polls.
        """
        from sase.agent.multi_prompt import MultiPrompt
        from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

        assert isinstance(multi, MultiPrompt)

        def _run() -> None:
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
                        self._schedule_agents_async_refresh  # type: ignore[attr-defined]
                    ),
                )
                self.call_later(self._schedule_agents_async_refresh)  # type: ignore[attr-defined]
                msg = f"Started {len(results)} agent(s) for {ctx.display_name}"
                self.call_later(lambda: self.notify(msg))  # type: ignore[attr-defined]
            except Exception:
                log.exception("Multi-prompt launch failed")
                self.call_later(  # type: ignore[attr-defined]
                    lambda: self.notify(  # type: ignore[attr-defined]
                        "Multi-prompt launch failed (see log)", severity="error"
                    )
                )

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        # Immediate feedback while agents launch in background.
        n = len(multi.segments)
        self.call_later(self._schedule_agents_async_refresh)  # type: ignore[attr-defined]
        self.notify(f"Launching {n} agent(s) for {ctx.display_name}...")  # type: ignore[attr-defined]
