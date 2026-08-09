"""Single prompt launch body for agent workflow actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._launch_body_impl import run_agent_launch_body
from ._launch_tasks import LaunchTaskOutcome
from ._types import PromptContext
from ..failure_messages import with_log_panel_hint

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.ace.patch import Patch
    from sase.ace.tui.modals import SelectionItem


class AgentLaunchBodyMixin:
    """Mixin providing the worker-thread launch body."""

    _bulk_patches: list[Patch] | None
    _prompt_context: PromptContext | None
    _last_custom_agent_selection: SelectionItem | None

    async def _run_agent_launch_body_async(
        self, prompt: str, ctx: PromptContext | None = None
    ) -> None:
        """Run :meth:`_run_agent_launch_body` in a worker thread.

        Keeps blocking I/O (disk reads, history writes, xprompt expansion)
        off the Textual event loop so ``j``/``k`` keystrokes entered
        immediately after submitting the launch are dispatched promptly.
        """
        import asyncio

        try:
            outcome = await asyncio.to_thread(self._run_agent_launch_body, prompt, ctx)
        except Exception as exc:
            log.exception("Agent launch body failed")
            # An exception escaped the launch body before any inner failed-launch
            # branch could run (e.g. a project-alias canonicalization conflict).
            # Preserve the submitted prompt so it stays recoverable from the
            # stash after the bar has been unmounted.
            from sase.history.prompt import record_failed_launch_prompt
            from sase.logs import log_launch_failure

            await asyncio.to_thread(
                record_failed_launch_prompt,
                prompt,
                project=ctx.project_name if ctx is not None else None,
            )
            await asyncio.to_thread(
                log_launch_failure,
                kind="single",
                display_name=ctx.display_name if ctx is not None else "agent launch",
                exc=exc,
                project=ctx.project_name if ctx is not None else None,
                workspace_num=ctx.workspace_num if ctx is not None else None,
                prompt_preview=prompt,
                stage="launch_body",
            )
            # The prompt was just stashed above; reflect it in the badge.
            self._schedule_prompt_stash_badge_refresh()  # type: ignore[attr-defined]
            self.notify(  # type: ignore[attr-defined]
                with_log_panel_hint("Agent launch failed"), severity="error"
            )
            return
        if outcome is None:
            return
        if outcome.results:
            self._handle_launch_results_delta(outcome.results)  # type: ignore[attr-defined]
        if outcome.request_agents_refresh:
            self.request_agents_refresh("launch")  # type: ignore[attr-defined]
        if outcome.schedule_agents_refresh:
            self._schedule_agents_async_refresh(source="launch")  # type: ignore[attr-defined]
        if outcome.refresh_notifications:
            refresh = getattr(self, "_refresh_notification_count", None)
            if callable(refresh):
                refresh()
        if outcome.severity in ("error", "warning"):
            # An inner failed-launch branch already stashed the prompt
            # synchronously; reflect the new row in the badge.
            self._schedule_prompt_stash_badge_refresh()  # type: ignore[attr-defined]
        for warning in outcome.warning_messages:
            self.notify(warning, severity="warning")  # type: ignore[attr-defined]
        if outcome.notify and outcome.message:
            self.notify(outcome.message, severity=outcome.severity)  # type: ignore[attr-defined]

    def _run_agent_launch_body(
        self, prompt: str, ctx: PromptContext | None = None
    ) -> LaunchTaskOutcome:
        """Heavy body of ``_finish_agent_launch``, run in a worker thread.

        Executes blocking I/O (VCS resolution, history writes, xprompt
        expansion, workflow dispatch) off the Textual event-loop thread.
        UI-touching sub-launch helpers that mutate widget state are marshalled
        back to the main thread via ``self.call_later``. Direct completion
        effects are returned for the task-queue completion callback.

        When ``ctx`` is given (the Phase 4 keep-bar single-pane submit) the body
        operates on that explicit snapshot and never touches
        ``self._prompt_context``, leaving the mounted stack's base context
        intact. When ``ctx`` is ``None`` the body reads the app's
        ``self._prompt_context`` and clears it on consumption, as before.
        """
        return run_agent_launch_body(self, prompt, ctx)
