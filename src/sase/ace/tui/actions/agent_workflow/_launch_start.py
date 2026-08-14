"""Prompt submission and launch-start handling for agent workflow actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._types import PromptContext

if TYPE_CHECKING:
    from sase.agent.prompt_placeholder_inputs import PromptInputPlan
    from sase.ace.tui.modals import SelectionItem


def _launch_toast_label(prompt: str, fallback: str) -> str:
    """Return the launch-toast label for *prompt*.

    The prompt bar's ``ctx`` is baked when the bar opens; cycling the bar text
    with ``<ctrl+p>`` to a different VCS ref only mutates the text, never the
    context. Deriving the label from the submitted text (cheap, lexical) keeps
    the "Launching agent for ..." toast honest about the cycled-to ref instead
    of the stale baked ``ctx.display_name``. Falls back to *fallback* when the
    prompt has no recognized leading VCS tag.
    """
    from sase.xprompt._parsing import (
        extract_project_from_vcs_tag,
        extract_vcs_workflow_tag,
    )

    tag = extract_vcs_workflow_tag(prompt.strip() + " ")
    if tag is not None:
        ref = extract_project_from_vcs_tag(tag)
        if ref:
            return ref
    return fallback


class AgentLaunchStartMixin:
    """Mixin providing prompt-submit launch setup."""

    _prompt_context: PromptContext | None
    _last_custom_agent_selection: SelectionItem | None

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
        if self._prompt_context is None:
            self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
            return

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
            self._collect_prompt_inputs_then_launch(prompt, plan, keep_bar)
            return
        if plan.declared is not None:
            # Only optional inputs: substitute their declared defaults so any
            # ``{{ name }}`` placeholders resolve, then launch (no modal).
            try:
                prompt = render_prompt_with_inputs(prompt, {})
            except PromptInputError as exc:
                self.notify(f"Input error: {exc}", severity="error")  # type: ignore[attr-defined]
                return

        self._launch_resolved_prompt(prompt, keep_bar=keep_bar)

    def _collect_prompt_inputs_then_launch(
        self, prompt: str, plan: PromptInputPlan, keep_bar: bool
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
            if values is None:
                self.notify("Input collection cancelled")  # type: ignore[attr-defined]
                return
            assert isinstance(values, PromptInputValues)
            record_prompt_placeholders(parse_yaml_front_matter(prompt)[1])
            try:
                resolved = apply_prompt_input_values(prompt, values)
            except PromptInputError as exc:
                self.notify(f"Input error: {exc}", severity="error")  # type: ignore[attr-defined]
                return
            self._launch_resolved_prompt(resolved, keep_bar=keep_bar)

        self.push_screen(  # type: ignore[attr-defined]
            InputCollectionModal(plan, agent_count=agent_count),
            _after,
        )

    def _launch_resolved_prompt(self, prompt: str, *, keep_bar: bool = False) -> None:
        """Launch *prompt* (inputs already resolved) in a worker thread.

        Unmounts the prompt bar immediately, then runs the heavy launch
        work (VCS resolution, history writes, xprompt expansion, subprocess
        spawn) in a tracked Textual worker thread so the Textual event loop
        stays responsive to keystrokes (notably ``j``/``k``) during the
        blocking I/O portion of the launch.

        ``keep_bar`` is set for a Phase 4 single-pane submit from a multi-pane
        stack: the bar stays mounted so the remaining panes can be submitted
        next. The mounted bar's ``_prompt_context`` is the immutable base for
        the stack, so this clones it (with a freshly reserved timestamp /
        workflow name) and hands the snapshot to the launch worker. That keeps
        the base intact for later submits and makes each launch's context
        independent of subsequent edits — avoiding any cross-submit races on the
        shared ``self._prompt_context``.

        Args:
            prompt: The user's prompt for the agent (inputs already substituted).
            keep_bar: Leave the prompt bar mounted and the base context intact
                (single-pane submit with panes remaining) instead of unmounting.
        """
        if self._prompt_context is None:
            self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
            return

        # Regenerate timestamp at launch time (not when prompt bar was opened)
        from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

        if keep_bar:
            import dataclasses

            ctx = dataclasses.replace(self._prompt_context)
        else:
            ctx = self._prompt_context
        ctx.timestamp = reserve_launch_timestamp_batch(1)[0]
        ctx.workflow_name = f"ace(run)-{ctx.timestamp}"

        # Unmount prompt bar first (transfers focus to the active tab's list
        # widget, see _transfer_focus_off_prompt_bar), then offload the
        # heavy launch path to a worker thread. The launch worker writes
        # the final non-cancelled history entry, so this path must NOT go
        # through the safety-net cancel save (sase-3q.2).
        #
        # In the keep_bar case the bar stays mounted and ``self._prompt_context``
        # remains the base, so the worker must operate on the explicit ``ctx``
        # snapshot rather than reading (and clearing) the shared base.
        if not keep_bar:
            self._unmount_prompt_bar_after_submit()  # type: ignore[attr-defined]
        from ...util.trace import set_trace_context

        set_trace_context(
            last_action="launch",
            last_action_display_name=ctx.display_name,
            last_action_ts=ctx.timestamp,
        )
        self.notify(  # type: ignore[attr-defined]
            f"Launching agent for {_launch_toast_label(prompt, ctx.display_name)}..."
        )

        launch_ctx = ctx if keep_bar else None
        self._submit_launch_proc(  # type: ignore[attr-defined]
            display_name=f"launch {ctx.display_name}",
            cl_name=ctx.display_name,
            project_file=ctx.project_file,
            dedup_key=f"launch:{ctx.workflow_name}",
            proc_callable=lambda: self._run_agent_launch_body(prompt, launch_ctx),  # type: ignore[attr-defined]
            # Recovery metadata: if the body raises before an inner failed-launch
            # branch runs (e.g. a project-alias canonicalization conflict), the
            # completion handler stashes this prompt so it stays recoverable.
            submitted_prompt=prompt,
        )
