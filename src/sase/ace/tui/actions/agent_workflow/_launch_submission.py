"""Accepted prompt submission for ACE agent launches."""

from __future__ import annotations

from collections.abc import Coroutine
from dataclasses import replace
import logging
from typing import TYPE_CHECKING, Any

from ._launch_submit_helpers import (
    dispatch_payload_from_prompt_context,
    launch_toast_label,
    schedule_submit_time_vcs_replay,
)
from ._pending_launch import (
    PendingLaunch,
    PendingLaunchStage,
    begin_pending_launch,
    call_pending_launch_from_worker,
    cancel_pending_launch,
    finish_pending_launch,
    flush_pending_launch_stashes,
    pending_launch_is_live,
    restore_pending_launch_prompt,
    set_pending_launch_stage,
)
from ._types import (
    PromptContext,
    PromptSessionId,
    current_prompt_session,
    invalidate_prompt_session,
)
from sase.xprompt._directive_scan import scan_dispatch_directive
from sase.xprompt._exceptions import DirectiveError

if TYPE_CHECKING:
    from sase.ace.patch import Patch

log = logging.getLogger(__name__)


class LaunchSubmissionMixin:
    """Mixin submitting accepted prompts to the durable launcher."""

    _prompt_context: PromptContext | None
    _bulk_patches: list[Patch] | None

    if TYPE_CHECKING:

        def _preflight_hold_confirm(self, launch_id: str) -> None: ...

    def _submit_resolved_launch(
        self,
        prompt: str,
        *,
        keep_bar: bool = False,
        extra_payload: dict[str, object] | None = None,
        owner_session_id: PromptSessionId | None = None,
    ) -> None:
        """Compatibility entry point for callers with no detached guard stage.

        The prompt-input pipeline accepts first and invokes its guards before
        continuing.  Existing bar-less and test callers that are already past
        those guards retain the original accept-and-submit behavior here.
        """
        launch = self._accept_resolved_launch(
            prompt,
            keep_bar=keep_bar,
            extra_payload=extra_payload,
            owner_session_id=owner_session_id,
        )
        if launch is not None:
            self._preflight_dispatch_pending_launch(
                launch.launch_id, continue_with_guards=False
            )

    def _preflight_dispatch_pending_launch(
        self, launch_id: str, *, continue_with_guards: bool = True
    ) -> None:
        """Preview a dispatch source after acceptance, before all other guards."""
        from ._pending_launch import pending_launch

        launch = pending_launch(self, launch_id)
        if launch is None:
            return
        try:
            scan = scan_dispatch_directive(launch.prompt)
        except DirectiveError as exc:
            self._abort_dispatch_pending_launch(launch, str(exc))
            return
        if scan is None:
            self._continue_after_dispatch_preview(
                launch, continue_with_guards=continue_with_guards
            )
            return

        payload = dispatch_payload_from_prompt_context(launch.context)
        set_pending_launch_stage(self, launch_id, PendingLaunchStage.DISPATCH_PREVIEW)

        def _work() -> None:
            preview: object | None = None
            error: str | None = None
            try:
                from sase.dispatch.launch import preview_dispatch_launch

                preview = preview_dispatch_launch(launch.prompt, payload=payload)
            except Exception as exc:  # source errors are returned to the draft
                error = str(exc)
            call_pending_launch_from_worker(
                self,
                self._complete_dispatch_pending_launch,
                launch_id,
                payload,
                preview,
                error,
                continue_with_guards,
            )

        run_worker = getattr(self, "run_worker", None)
        try:
            if callable(run_worker):
                run_worker(
                    _work,
                    name=f"dispatch-launch-preflight:{launch_id}",
                    thread=True,
                    exclusive=False,
                    group=f"dispatch-launch-preflight:{launch_id}",
                )
            else:
                _work()
        except Exception as exc:
            self._abort_dispatch_pending_launch(launch, str(exc))

    def _complete_dispatch_pending_launch(
        self,
        launch_id: str,
        payload: dict[str, object],
        preview: object | None,
        error: str | None,
        continue_with_guards: bool,
    ) -> None:
        """Record one completed preview and advance its live pending launch."""
        from ._pending_launch import pending_launch

        launch = pending_launch(self, launch_id)
        if launch is None:
            return
        if error is not None or preview is None:
            self._abort_dispatch_pending_launch(launch, error or "no source preview")
            return
        recorder = getattr(self, "_record_dispatch_launch_preview", None)
        if callable(recorder):
            recorder(preview, prompt=launch.prompt, payload=payload)
        self._continue_after_dispatch_preview(
            launch, continue_with_guards=continue_with_guards
        )

    def _continue_after_dispatch_preview(
        self, launch: PendingLaunch, *, continue_with_guards: bool
    ) -> None:
        if continue_with_guards:
            self._preflight_hold_confirm(launch.launch_id)
        else:
            self._continue_pending_launch(launch)

    def _abort_dispatch_pending_launch(self, launch: PendingLaunch, error: str) -> None:
        """Return a blocked dispatch launch and annotate its restored prompt."""
        cancel_pending_launch(self, launch)
        message = f"source blocked: {error}"
        restored = restore_pending_launch_prompt(
            self,
            launch,
            reason=f"Dispatch not submitted: {error}",
            explicit=False,
        )
        if not restored:
            return

        def _apply_override() -> None:
            mounted = getattr(self, "_mounted_prompt_bar", None)
            bar = mounted() if callable(mounted) else None
            setter = getattr(bar, "_set_dispatch_preflight_override", None)
            if callable(setter):
                setter(launch.prompt, message, "error")

        after_refresh = getattr(self, "call_after_refresh", None)
        if callable(after_refresh):
            after_refresh(_apply_override)
        else:
            _apply_override()

    def _accept_resolved_launch(
        self,
        prompt: str,
        *,
        keep_bar: bool = False,
        extra_payload: dict[str, object] | None = None,
        owner_session_id: PromptSessionId | None = None,
    ) -> PendingLaunch | None:
        """Accept *prompt* and release its bar before detached preflights run.

        Acceptance snapshots everything the launch needs, unmounts the bar
        (unless *keep_bar*), and registers a pending launch (proc row plus
        ``PREPARING`` record) before anything can wait. Nothing after this
        point depends on the bar or its prompt session.  Hold and provider
        checks continue from the returned record; only their successful final
        path enters :meth:`_continue_pending_launch`.
        """
        session = current_prompt_session(self)
        if session is None or (
            owner_session_id is not None and session.session_id != owner_session_id
        ):
            self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
            return None

        # A bulk fan-out always consumes the whole bar, whatever the pane mode.
        bulk_patches = tuple(getattr(self, "_bulk_patches", None) or ())
        keep_bar = keep_bar and not bulk_patches
        launch = begin_pending_launch(
            self,
            prompt=prompt,
            context=session.context,
            keep_bar=keep_bar,
            extra_payload=extra_payload,
            bulk_patches=bulk_patches,
            relaunch_operation=session.relaunch_operation,
            stage=PendingLaunchStage.HOLD_CHECK,
        )

        # Unmount the prompt bar first (transfers focus to the active tab's
        # list widget, see _transfer_focus_off_prompt_bar); the out-of-process
        # launch cannot release UI state for us, so the UI thread owns and
        # releases the prompt context here. The launch worker writes the final
        # non-cancelled history entry, so this path must NOT go through the
        # safety-net cancel save (sase-3q.2).
        #
        # In the keep_bar case the bar stays mounted and ``self._prompt_context``
        # remains the base; the pending launch carries its own context
        # snapshot, so this submit does not mutate the base later panes use.
        if not keep_bar:
            invalidate_prompt_session(self, session.session_id, clear_context=False)
            self._unmount_prompt_bar_after_submit()  # type: ignore[attr-defined]
            self._prompt_context = None
        if bulk_patches:
            self._bulk_patches = None
            self._clear_bulk_patch_marks()  # type: ignore[attr-defined]
        self.notify(  # type: ignore[attr-defined]
            f"Launching agent for {launch_toast_label(prompt, launch.context.display_name)}..."
        )
        return launch

    def _continue_pending_launch(self, launch: PendingLaunch) -> None:
        """Run the remaining stages of *launch*, parking it behind open barriers."""
        from ._relaunch_barrier import hold_launch_for_relaunch_cleanup

        if not pending_launch_is_live(self, launch.launch_id):
            log.debug("Dropping submission for cancelled pending launch")
            return

        if hold_launch_for_relaunch_cleanup(
            self,
            lambda: self._continue_pending_launch(launch),
            launch_id=launch.launch_id,
            operation=launch.relaunch_operation,
        ):
            return

        set_pending_launch_stage(self, launch.launch_id, PendingLaunchStage.SUBMITTING)
        if launch.bulk_patches:
            self._submit_bulk_pending_launch(launch)  # type: ignore[attr-defined]
            return
        self._submit_single_pending_launch(launch)

    def _submit_single_pending_launch(self, launch: PendingLaunch) -> None:
        """Submit one durable ``sase run`` for *launch* from its stored snapshot."""
        # Regenerate timestamp at launch time, not when prompt bar was opened.
        from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

        ctx = replace(launch.context)
        ctx.timestamp = reserve_launch_timestamp_batch(1)[0]
        ctx.workflow_name = f"ace(run)-{ctx.timestamp}"

        from ...util.trace import set_trace_context

        set_trace_context(
            last_action="launch",
            last_action_display_name=ctx.display_name,
            last_action_ts=ctx.timestamp,
        )
        payload = dispatch_payload_from_prompt_context(ctx)
        if launch.extra_payload:
            payload.update(launch.extra_payload)

        proc_info = self._submit_launch_proc(  # type: ignore[attr-defined]
            display_name=f"launch {ctx.display_name}",
            cl_name=ctx.display_name,
            project_file=ctx.project_file,
            prompt=launch.prompt,
            dedup_key=f"launch:{ctx.workflow_name}",
            extra_payload=payload,
            submitted_prompt=launch.prompt,
        )
        if proc_info is None:
            cancel_pending_launch(self, launch)
            restore_pending_launch_prompt(
                self, launch, reason="Launch not submitted", explicit=False
            )
            return
        finish_pending_launch(
            self,
            launch,
            proc_ids=(proc_info.proc_id,),
            submitted_prompts={proc_info.proc_id: launch.prompt},
        )
        schedule_submit_time_vcs_replay(self, (launch.prompt,))

    def _flush_pending_launch_stashes(self) -> Coroutine[Any, Any, None]:
        """Quit-time flush: stash every prompt that is still a pending launch."""
        return flush_pending_launch_stashes(self)


__all__ = ["LaunchSubmissionMixin"]
