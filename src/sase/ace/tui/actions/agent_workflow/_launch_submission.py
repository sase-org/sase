"""Accepted prompt submission for ACE agent launches."""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from typing import TYPE_CHECKING

from ._launch_records import push_launch_record
from ._launch_submit_helpers import (
    launch_record_context_from_prompt_context,
    launch_toast_label,
    record_submit_time_vcs_replay,
)
from ._types import (
    PromptContext,
    PromptSessionId,
    RelaunchOperation,
    current_prompt_session,
    invalidate_prompt_session,
    prompt_session_is_live,
)

if TYPE_CHECKING:
    from sase.ace.patch import Patch

log = logging.getLogger(__name__)


@dataclass
class AcceptedLaunchSubmission:
    """One prompt submission accepted by the UI but possibly parked."""

    prompt: str
    context: PromptContext
    keep_bar: bool
    extra_payload: dict[str, object] | None
    bulk_patches: tuple[Patch, ...]
    owner_id: PromptSessionId | None
    relaunch_operation: RelaunchOperation | None
    submitted: bool = False


class LaunchSubmissionMixin:
    """Mixin submitting accepted prompts to the durable launcher."""

    _prompt_context: PromptContext | None
    _bulk_patches: list[Patch] | None

    def _submit_resolved_launch(
        self,
        prompt: str,
        *,
        keep_bar: bool = False,
        extra_payload: dict[str, object] | None = None,
        owner_session_id: PromptSessionId | None = None,
        accepted: object | None = None,
    ) -> None:
        """Unmount (unless *keep_bar*) and submit the durable ``sase run``.

        Refuses to submit while a relaunch cleanup barrier is still open (a
        ``,x`` kill/dismiss persistence proc that has not yet settled): the
        submit is parked and replayed once every open barrier settles, so no
        durable ``sase run`` can race a late bundle write that would resurrect
        the name it is about to reuse. See ``_relaunch_barrier``.
        """
        from ._relaunch_barrier import hold_launch_for_relaunch_cleanup

        accepted_submission: AcceptedLaunchSubmission | None
        if accepted is None:
            accepted_submission = None
        elif isinstance(accepted, AcceptedLaunchSubmission):
            accepted_submission = accepted
        else:
            raise TypeError("accepted launch submission has unexpected type")

        if accepted_submission is None:
            session = current_prompt_session(self)
            if session is None or (
                owner_session_id is not None and session.session_id != owner_session_id
            ):
                self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
                return
            owner_session_id = session.session_id
            if not keep_bar and session.accepted_whole_bar_submit:
                log.debug("Dropping duplicate whole-bar launch submission")
                return
            if not keep_bar:
                session.accepted_whole_bar_submit = True
            accepted_submission = AcceptedLaunchSubmission(
                prompt=prompt,
                context=replace(session.context),
                keep_bar=keep_bar,
                extra_payload=(
                    dict(extra_payload) if extra_payload is not None else None
                ),
                bulk_patches=tuple(getattr(self, "_bulk_patches", None) or ()),
                owner_id=owner_session_id,
                relaunch_operation=session.relaunch_operation,
            )

        if accepted_submission.submitted:
            return

        if not prompt_session_is_live(self, accepted_submission.owner_id):
            log.debug("Dropping launch submission for retired prompt session")
            return

        if hold_launch_for_relaunch_cleanup(
            self,
            lambda: self._submit_resolved_launch(
                accepted_submission.prompt,
                keep_bar=accepted_submission.keep_bar,
                extra_payload=accepted_submission.extra_payload,
                owner_session_id=accepted_submission.owner_id,
                accepted=accepted_submission,
            ),
            owner_id=accepted_submission.owner_id,
            operation=accepted_submission.relaunch_operation,
        ):
            return

        if not prompt_session_is_live(self, accepted_submission.owner_id):
            log.debug("Dropping launch submission for retired prompt session")
            return

        bulk_patches = accepted_submission.bulk_patches
        if bulk_patches:
            accepted_submission.submitted = True
            self._submit_bulk_resolved_launch(  # type: ignore[attr-defined]
                accepted_submission.prompt,
                list(bulk_patches),
                keep_bar=accepted_submission.keep_bar,
                extra_payload=accepted_submission.extra_payload,
            )
            return

        # Regenerate timestamp at launch time, not when prompt bar was opened.
        from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

        ctx = replace(accepted_submission.context)
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
        accepted_submission.submitted = True
        if not accepted_submission.keep_bar:
            invalidate_prompt_session(
                self, accepted_submission.owner_id, clear_context=False
            )
            self._unmount_prompt_bar_after_submit()  # type: ignore[attr-defined]
            self._prompt_context = None
        from ...util.trace import set_trace_context

        set_trace_context(
            last_action="launch",
            last_action_display_name=ctx.display_name,
            last_action_ts=ctx.timestamp,
        )
        self.notify(  # type: ignore[attr-defined]
            "Launching agent for "
            f"{launch_toast_label(accepted_submission.prompt, ctx.display_name)}..."
        )

        payload: dict[str, object] = {
            "display_name": ctx.display_name,
            "project_name": ctx.project_name,
            "workflow_name": ctx.workflow_name,
        }
        if accepted_submission.extra_payload:
            payload.update(accepted_submission.extra_payload)

        proc_info = self._submit_launch_proc(  # type: ignore[attr-defined]
            display_name=f"launch {ctx.display_name}",
            cl_name=ctx.display_name,
            project_file=ctx.project_file,
            prompt=accepted_submission.prompt,
            dedup_key=f"launch:{ctx.workflow_name}",
            extra_payload=payload,
            submitted_prompt=accepted_submission.prompt,
        )
        if proc_info is not None:
            push_launch_record(
                self,
                proc_ids=(proc_info.proc_id,),
                prompt=accepted_submission.prompt,
                context=launch_record_context_from_prompt_context(ctx),
                submitted_prompts={proc_info.proc_id: accepted_submission.prompt},
            )
            record_submit_time_vcs_replay(accepted_submission.prompt)


__all__ = [
    "AcceptedLaunchSubmission",
    "LaunchSubmissionMixin",
]
