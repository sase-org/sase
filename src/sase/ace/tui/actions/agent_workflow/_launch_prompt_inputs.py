"""Prompt input collection before ACE agent launch submission."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._launch_provider_guard import LaunchProviderGuardMixin
from ._types import (
    PromptContext,
    PromptSessionId,
    current_prompt_session,
    prompt_session_is_live,
)

if TYPE_CHECKING:
    from sase.agent.prompt_placeholder_inputs import PromptInputPlan


class LaunchPromptInputMixin(LaunchProviderGuardMixin):
    """Mixin resolving prompt placeholders before launch submission."""

    _prompt_context: PromptContext | None

    def _finish_agent_launch(self, prompt: str, *, keep_bar: bool = False) -> None:
        """Complete agent launch with the given prompt.

        Anything the prompt needs collected is gathered on one page first: every
        unique raw ``<placeholder>`` written in the body (backticked and fenced
        ones stay literal) plus any ``input:`` arguments the frontmatter
        declares. Required declared inputs and placeholders open the Prompt
        Inputs panel; optional declared inputs fall back to their declared
        defaults. Values are substituted before the normal launch proceeds (see
        :func:`sase.agent.prompt_placeholder_inputs.apply_prompt_input_values`).
        Prompts with nothing to collect launch immediately.

        Args:
            prompt: The user's prompt for the agent.
            keep_bar: Leave the prompt bar mounted and the base context intact
                (single-pane submit with panes remaining) instead of unmounting.
        """
        session = current_prompt_session(self)
        if session is None:
            self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
            return
        owner_id = session.session_id

        from sase.agent.prompt_inputs import (
            PromptInputError,
            render_prompt_with_inputs,
        )
        from sase.agent.prompt_placeholder_inputs import build_prompt_input_plan

        plan = build_prompt_input_plan(prompt)
        if plan.needs_collection:
            # Collect on the UI thread, then launch from the modal callback. The
            # prompt bar stays mounted so a cancel returns the user to their
            # prompt.
            self._collect_prompt_inputs_then_launch(
                prompt,
                plan,
                keep_bar,
                owner_session_id=owner_id,
            )
            return
        if plan.declared is not None:
            # Only optional inputs: substitute their declared defaults so any
            # ``{{ name }}`` placeholders resolve, then launch (no modal).
            try:
                prompt = render_prompt_with_inputs(prompt, {})
            except PromptInputError as exc:
                self.notify(f"Input error: {exc}", severity="error")  # type: ignore[attr-defined]
                self._release_prompt_context_if_no_bar_mounted()
                return

        self._launch_resolved_prompt(
            prompt,
            keep_bar=keep_bar,
            owner_session_id=owner_id,
        )

    def _collect_prompt_inputs_then_launch(
        self,
        prompt: str,
        plan: PromptInputPlan,
        keep_bar: bool,
        *,
        owner_session_id: PromptSessionId | None,
    ) -> None:
        """Show the Prompt Inputs panel, then launch with substituted values.

        On confirm, the *pre-substitution* body is recorded in the common
        placeholder store so the tags the user wrote keep feeding the ``<``
        completion menu even though prompt history stores what actually ran.

        Cancelling the panel leaves the prompt bar mounted and launches nothing.
        """
        from sase.agent.multi_prompt import parse_multi_prompt
        from sase.agent.prompt_inputs import PromptInputError
        from sase.agent.prompt_placeholder_inputs import (
            PromptInputValues,
            apply_prompt_input_values,
        )
        from sase.ace.tui.modals import InputCollectionModal
        from sase.history.prompt_placeholders import record_prompt_placeholders
        from sase.xprompt.loader_parsing import parse_yaml_front_matter

        agent_count = max(1, len(parse_multi_prompt(prompt).segments))

        def _after(values: object) -> None:
            if not prompt_session_is_live(self, owner_session_id):
                self.notify(  # type: ignore[attr-defined]
                    "Launch cancelled; the prompt bar was closed while collecting inputs.",
                    severity="warning",
                )
                return
            if values is None:
                self.notify("Input collection cancelled")  # type: ignore[attr-defined]
                self._release_prompt_context_if_no_bar_mounted()
                return
            assert isinstance(values, PromptInputValues)
            record_prompt_placeholders(parse_yaml_front_matter(prompt)[1])
            try:
                resolved = apply_prompt_input_values(prompt, values)
            except PromptInputError as exc:
                self.notify(f"Input error: {exc}", severity="error")  # type: ignore[attr-defined]
                self._release_prompt_context_if_no_bar_mounted()
                return
            self._launch_resolved_prompt(
                resolved,
                keep_bar=keep_bar,
                owner_session_id=owner_session_id,
            )

        self.push_screen(  # type: ignore[attr-defined]
            InputCollectionModal(plan, agent_count=agent_count),
            _after,
        )

    def _launch_resolved_prompt(
        self,
        prompt: str,
        *,
        keep_bar: bool = False,
        owner_session_id: PromptSessionId | None = None,
    ) -> None:
        """Launch *prompt* (inputs already resolved) via durable ``sase run``.

        Runs the hard-disable provider guard first while the prompt bar is
        still mounted. Only a launch that is actually submitted unmounts the
        bar. The empty-disable path is synchronous and then submits argv-only
        ``sase run`` to the durable supervisor so the Textual event loop stays
        responsive to keystrokes (notably ``j``/``k``) during the out-of-process
        launch.

        ``keep_bar`` is set for a Phase 4 single-pane submit from a multi-pane
        stack: the bar stays mounted so the remaining panes can be submitted
        next. The mounted bar's ``_prompt_context`` is the immutable base for
        the stack, so this clones it (with a freshly reserved timestamp /
        workflow name) and puts that identity on the submitted payload. That
        keeps the base intact for later submits and makes each launch's context
        independent of subsequent edits, avoiding cross-submit races on the
        shared ``self._prompt_context``.

        Args:
            prompt: The user's prompt for the agent (inputs already substituted).
            keep_bar: Leave the prompt bar mounted and the base context intact
                (single-pane submit with panes remaining) instead of unmounting.
        """
        if not prompt_session_is_live(self, owner_session_id):
            self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
            return

        self._preflight_provider_disables(
            prompt,
            keep_bar,
            owner_session_id=owner_session_id,
        )

    def _release_prompt_context_if_no_bar_mounted(self) -> None:
        """Clear bar-less prompt state without destroying a mounted draft.

        Prompt-input collection can be reached after opening a prompt directly
        in an external editor, where no ``PromptInputBar`` exists to cancel.
        If a bar is mounted, leave its context alone so the user's draft
        survives modal cancel and input-error paths.
        """
        mounted_prompt_bar = getattr(self, "_mounted_prompt_bar", None)
        if callable(mounted_prompt_bar):
            if mounted_prompt_bar() is not None:
                return
        else:
            query = getattr(self, "query", None)
            if query is None:
                return
            from ...widgets import PromptInputBar

            if query(PromptInputBar):
                return
        self._prompt_context = None


__all__ = ["LaunchPromptInputMixin"]
