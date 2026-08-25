"""Prompt submission and launch-start handling for agent workflow actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._launch_provider_guard import LaunchProviderGuardMixin
from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.patch import Patch
    from sase.agent.prompt_placeholder_inputs import PromptInputPlan

log = logging.getLogger(__name__)


def _submitted_vcs_xprompt_prefix(prompt: str) -> str | None:
    """Return ``#<workflow>:<ref>`` for *prompt*'s leading VCS tag, if any."""
    from sase.xprompt._parsing import (
        extract_project_from_vcs_tag,
        extract_vcs_workflow_tag,
    )

    tag = extract_vcs_workflow_tag(prompt.strip() + " ")
    if tag is None:
        return None
    ref = extract_project_from_vcs_tag(tag)
    if not ref:
        return None
    workflow_type = _vcs_workflow_type_from_tag(tag)
    if not workflow_type:
        return None
    return f"#{workflow_type}:{ref}"


def _vcs_workflow_type_from_tag(tag: str) -> str | None:
    """Return the workflow-type prefix (e.g. ``"gh"``) of a leading VCS tag."""
    body = tag.strip()
    if not body.startswith("#"):
        return None
    body = body[1:]
    for suffix in ("!!", "??"):
        idx = body.find(suffix)
        if idx != -1:
            body = body[:idx] + body[idx + len(suffix) :]
            break
    for sep in ("(", ":", "_", "+"):
        idx = body.find(sep)
        if idx != -1:
            return body[:idx] or None
    return body or None


def _launch_toast_label(prompt: str, fallback: str) -> str:
    """Return the launch-toast label for *prompt*.

    The prompt bar's ``ctx`` is baked when the bar opens; cycling the bar text
    with ``<ctrl+p>`` to a different VCS ref only mutates the text, never the
    context. Deriving the label from the submitted text (cheap, lexical) keeps
    the "Launching agent for ..." toast honest about the cycled-to ref instead
    of the stale baked ``ctx.display_name``. Falls back to *fallback* when the
    prompt has no recognized leading VCS tag.
    """
    from sase.xprompt._parsing import extract_project_from_vcs_tag

    prefix = _submitted_vcs_xprompt_prefix(prompt)
    if prefix is None:
        return fallback
    return extract_project_from_vcs_tag(prefix) or fallback


def _record_submit_time_vcs_replay(prompt: str) -> None:
    """Refresh the Ctrl+Space MRU from the prompt actually submitted.

    ``record_vcs_xprompt_usage`` already drops the implicit ``#git:home``
    default and known non-launchable projects, so this is safe to call for
    every ACE submit including home-mode and bulk fan-out.
    """
    prefix = _submitted_vcs_xprompt_prefix(prompt)
    if prefix is None:
        return
    try:
        from sase.history.vcs_xprompt_mru import record_vcs_xprompt_usage

        record_vcs_xprompt_usage(prefix)
    except Exception:
        log.debug("Failed to refresh Ctrl+Space replay target", exc_info=True)


class AgentLaunchStartMixin(LaunchProviderGuardMixin):
    """Mixin providing prompt-submit launch setup."""

    _prompt_context: PromptContext | None
    _bulk_patches: list[Patch] | None

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
                self._release_prompt_context_if_no_bar_mounted()
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
            self._launch_resolved_prompt(resolved, keep_bar=keep_bar)

        self.push_screen(  # type: ignore[attr-defined]
            InputCollectionModal(plan, agent_count=agent_count),
            _after,
        )

    def _launch_resolved_prompt(self, prompt: str, *, keep_bar: bool = False) -> None:
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
        keeps the base intact for later submits and makes each launch's
        context independent of subsequent edits — avoiding any cross-submit
        races on the shared ``self._prompt_context``.

        Args:
            prompt: The user's prompt for the agent (inputs already substituted).
            keep_bar: Leave the prompt bar mounted and the base context intact
                (single-pane submit with panes remaining) instead of unmounting.
        """
        if self._prompt_context is None:
            self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
            return

        self._preflight_provider_disables(prompt, keep_bar)

    def _submit_resolved_launch(
        self,
        prompt: str,
        *,
        keep_bar: bool = False,
        extra_payload: dict[str, object] | None = None,
    ) -> None:
        """Unmount (unless *keep_bar*) and submit the durable ``sase run``.

        Refuses to submit while a relaunch cleanup barrier is still open (a
        ``,x`` kill/dismiss persistence proc that has not yet settled): the
        submit is parked and replayed once every open barrier settles, so no
        durable ``sase run`` can race a late bundle write that would
        resurrect the name it is about to reuse. See ``_relaunch_barrier``.
        """
        from ._relaunch_barrier import hold_launch_for_relaunch_cleanup

        if hold_launch_for_relaunch_cleanup(
            self,
            lambda: self._submit_resolved_launch(
                prompt, keep_bar=keep_bar, extra_payload=extra_payload
            ),
        ):
            return

        if self._prompt_context is None:
            self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
            return

        bulk_patches = getattr(self, "_bulk_patches", None)
        if bulk_patches:
            self._submit_bulk_resolved_launch(
                prompt,
                list(bulk_patches),
                keep_bar=keep_bar,
                extra_payload=extra_payload,
            )
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
        # widget, see _transfer_focus_off_prompt_bar), then submit argv-only
        # ``sase run`` to the durable supervisor. The out-of-process launch
        # cannot release UI state for us, so the UI thread owns and releases
        # the prompt context here. The launch worker writes the final
        # non-cancelled history entry, so this path must NOT go through the
        # safety-net cancel save (sase-3q.2).
        #
        # In the keep_bar case the bar stays mounted and ``self._prompt_context``
        # remains the base. ``ctx`` is a snapshot with a freshly reserved
        # timestamp / workflow name so this submit does not mutate the base
        # that later panes still use.
        if not keep_bar:
            self._unmount_prompt_bar_after_submit()  # type: ignore[attr-defined]
            self._prompt_context = None
        from ...util.trace import set_trace_context

        set_trace_context(
            last_action="launch",
            last_action_display_name=ctx.display_name,
            last_action_ts=ctx.timestamp,
        )
        self.notify(  # type: ignore[attr-defined]
            f"Launching agent for {_launch_toast_label(prompt, ctx.display_name)}..."
        )

        payload: dict[str, object] = {
            "display_name": ctx.display_name,
            "project_name": ctx.project_name,
            "workflow_name": ctx.workflow_name,
        }
        if extra_payload:
            payload.update(extra_payload)

        submitted = self._submit_launch_proc(  # type: ignore[attr-defined]
            display_name=f"launch {ctx.display_name}",
            cl_name=ctx.display_name,
            project_file=ctx.project_file,
            prompt=prompt,
            dedup_key=f"launch:{ctx.workflow_name}",
            extra_payload=payload,
            submitted_prompt=prompt,
        )
        if submitted:
            _record_submit_time_vcs_replay(prompt)

    def _submit_bulk_resolved_launch(
        self,
        prompt: str,
        patches: list[Patch],
        *,
        keep_bar: bool = False,
        extra_payload: dict[str, object] | None = None,
    ) -> None:
        """Submit one durable ``sase run`` per marked Patch.

        The shared prompt is rewritten with each Patch's VCS prefix so every
        launch carries that Patch's project/cl context. ``launch_units`` from
        the provider guard is dropped: each child must parse its own
        per-Patch prompt rather than replaying the unprefixed unit list.
        """
        del keep_bar
        self._bulk_patches = None  # type: ignore[attr-defined]
        self._unmount_prompt_bar_after_submit()  # type: ignore[attr-defined]
        self._prompt_context = None
        self._clear_bulk_patch_marks()

        n = len(patches)
        if n == 0:
            self.notify("No bulk patches", severity="error")  # type: ignore[attr-defined]
            return

        from sase.core.agent_launch_facade import reserve_launch_timestamp_batch
        from ...util.trace import set_trace_context

        timestamps = reserve_launch_timestamp_batch(n)
        set_trace_context(
            last_action="launch",
            last_action_display_name=f"bulk {n} Patches",
            last_action_ts=timestamps[0],
        )
        self.notify(f"Launching {n} agent(s)...")  # type: ignore[attr-defined]

        launched = 0
        failed = 0
        shared_extra = {
            key: value
            for key, value in dict(extra_payload or {}).items()
            if key != "launch_units"
        }
        for index, patch in enumerate(patches):
            slot = self._submit_one_bulk_patch(
                prompt,
                patch,
                timestamp=timestamps[index],
                extra_payload=shared_extra,
                slot_index=index,
                slot_count=n,
            )
            if slot:
                launched += 1
            else:
                failed += 1

        if failed:
            self.notify(  # type: ignore[attr-defined]
                f"Started {launched} agent(s), {failed} failed",
                severity="warning",
            )

    def _submit_one_bulk_patch(
        self,
        prompt: str,
        patch: Patch,
        *,
        timestamp: str,
        extra_payload: dict[str, object],
        slot_index: int,
        slot_count: int,
    ) -> bool:
        """Submit one marked-Patch launch. Return whether it was accepted."""
        import os

        from sase.ace.patch.project_spec_path import preferred_project_spec_path
        from sase.core.paths import sase_projects_dir
        from sase.project_display_names import humanize_cl_name
        from sase.workspace_provider import detect_workflow_type
        from sase.xprompt import replace_vcs_workflow_tags

        cl_name = patch.name
        project_name = patch.project_name or patch.project_basename
        project_file = patch.file_path
        if not project_file or not os.path.isfile(project_file):
            if project_name:
                project_file = preferred_project_spec_path(
                    str(sase_projects_dir() / project_name),
                    project_name,
                )
            if not project_file or not os.path.isfile(project_file):
                _log_bulk_item_failure(
                    FileNotFoundError(f"No project file for {cl_name}"),
                    cl_name=cl_name,
                    project_name=project_name,
                    prompt=prompt,
                    slot_index=slot_index,
                    slot_count=slot_count,
                    stage="project_file",
                    project_file=project_file or "",
                )
                return False

        try:
            workflow_type = detect_workflow_type(project_file)
        except Exception as exc:
            _log_bulk_item_failure(
                exc,
                cl_name=cl_name,
                project_name=project_name,
                prompt=prompt,
                slot_index=slot_index,
                slot_count=slot_count,
                stage="workflow_type",
                project_file=project_file,
            )
            return False

        cl_prompt = replace_vcs_workflow_tags(
            prompt,
            f"#{workflow_type}:{cl_name}",
        )
        display_name = humanize_cl_name(cl_name)
        workflow_name = f"ace(run)-{timestamp}"
        payload: dict[str, object] = dict(extra_payload)
        payload.update(
            {
                "display_name": display_name,
                "project_name": project_name,
                "workflow_name": workflow_name,
            }
        )
        submitted = bool(
            self._submit_launch_proc(  # type: ignore[attr-defined]
                display_name=f"launch {display_name}",
                cl_name=cl_name,
                project_file=project_file,
                prompt=cl_prompt,
                dedup_key=f"launch:{workflow_name}",
                extra_payload=payload,
                submitted_prompt=cl_prompt,
            )
        )
        if submitted:
            _record_submit_time_vcs_replay(cl_prompt)
        return submitted

    def _clear_bulk_patch_marks(self) -> None:
        """Drop Patch marks after a bulk submit so the UI matches reality."""
        targets = getattr(self, "_artifacts_marked_targets", None)
        if isinstance(targets, dict):
            targets["patches"] = set()
        refresh = getattr(self, "_refresh_display", None)
        if callable(refresh):
            refresh()

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


def _log_bulk_item_failure(
    exc: BaseException,
    *,
    cl_name: str,
    project_name: str,
    prompt: str,
    slot_index: int,
    slot_count: int,
    stage: str,
    project_file: str,
) -> None:
    """Durably record one skipped Patch in a bulk launch."""
    log.warning("Bulk launch skipped %s at %s: %s", cl_name, stage, exc)
    try:
        from sase.logs import log_launch_failure

        log_launch_failure(
            kind="bulk",
            display_name=cl_name,
            exc=exc,
            project=project_name,
            prompt_preview=prompt,
            slot_index=slot_index,
            slot_count=slot_count,
            stage=stage,
            project_file=project_file,
        )
    except Exception:
        log.debug("Failed to persist bulk-item launch failure", exc_info=True)
