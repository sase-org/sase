"""Prompt submission and launch-start handling for agent workflow actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._types import PromptContext

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.ace.tui.modals import SelectionItem


class AgentLaunchStartMixin:
    """Mixin providing prompt-submit launch setup."""

    _prompt_context: PromptContext | None
    _last_custom_agent_selection: SelectionItem | None

    def _finish_agent_launch(self, prompt: str) -> None:
        """Complete agent launch with the given prompt.

        Unmounts the prompt bar immediately, then runs the heavy launch
        work (VCS resolution, history writes, xprompt expansion, subprocess
        spawn) in a worker thread via ``asyncio.to_thread`` so the Textual
        event loop stays responsive to keystrokes (notably ``j``/``k``)
        during the blocking I/O portion of the launch.

        Args:
            prompt: The user's prompt for the agent.
        """
        if self._prompt_context is None:
            self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
            return

        from sase.agent.launch_validation import (
            force_reuse_owner_names,
            rewrite_force_reuse_name_directives,
            wipe_names_for_forced_reuse,
        )

        force_reuse_names = force_reuse_owner_names([prompt])
        if force_reuse_names:
            try:
                wipe_names_for_forced_reuse(force_reuse_names)
            except Exception:
                log.exception("Forced agent-name reuse wipe failed")
                self.notify(  # type: ignore[attr-defined]
                    "Agent name reuse failed (see log)", severity="error"
                )
                return
            prompt = rewrite_force_reuse_name_directives(prompt)

        # Regenerate timestamp at launch time (not when prompt bar was opened)
        from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

        ctx = self._prompt_context
        ctx.timestamp = reserve_launch_timestamp_batch(1)[0]
        ctx.workflow_name = f"ace(run)-{ctx.timestamp}"

        # Unmount prompt bar first (transfers focus to the active tab's list
        # widget, see _transfer_focus_off_prompt_bar), then offload the
        # heavy launch path to a worker thread. The launch worker writes
        # the final non-cancelled history entry, so this path must NOT go
        # through the safety-net cancel save (sase-3q.2).
        self._unmount_prompt_bar_after_submit()  # type: ignore[attr-defined]
        self.notify(f"Launching agent for {ctx.display_name}...")  # type: ignore[attr-defined]

        self.call_later(self._run_agent_launch_body_async, prompt)  # type: ignore[attr-defined]
