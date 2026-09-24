"""Pending launches: accepted prompts that finish launching without the bar.

Pressing Enter in the prompt bar *accepts* the launch. From that instant the
bar is gone and the launch continues as a :class:`PendingLaunch`: a snapshot of
everything the durable ``sase run`` needs, a placeholder row in the proc
indicator / Procs tab, and a ``PREPARING`` launch record so ``,X`` can undo it
before anything was submitted. The durable proc's own row takes over at submit
(:func:`finish_pending_launch`).

Every abort path gives the prompt back through
:func:`restore_pending_launch_prompt`, and quitting stashes whatever is still
pending (:func:`flush_pending_launch_stashes`).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ._launch_records import (
    LaunchRecord,
    attach_launch_record_procs,
    discard_launch_record,
    push_launch_record,
)
from ._launch_submit_helpers import launch_record_context_from_prompt_context
from ._types import PromptContext, RelaunchOperation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sase.ace.patch import Patch

log = logging.getLogger(__name__)

_QUIT_STASH_TIMEOUT_SECONDS = 3.0


class PendingLaunchStage(StrEnum):
    """Where an accepted launch is in its post-acceptance pipeline."""

    DISPATCH_PREVIEW = "dispatch_preview"
    HOLD_CHECK = "hold_check"
    HOLD_CONFIRM = "hold_confirm"
    PROVIDER_CHECK = "provider_check"
    PROVIDER_DECISION = "provider_decision"
    WAITING_CLEANUP = "waiting_cleanup"
    WAITING_LAST_LAUNCH = "waiting_last_launch"
    SUBMITTING = "submitting"


_STAGE_ROW_MESSAGES: dict[PendingLaunchStage, str] = {
    PendingLaunchStage.DISPATCH_PREVIEW: "checking dispatch source",
    PendingLaunchStage.HOLD_CHECK: "checking %hold",
    PendingLaunchStage.HOLD_CONFIRM: "waiting for %hold confirmation",
    PendingLaunchStage.PROVIDER_CHECK: "checking providers",
    PendingLaunchStage.PROVIDER_DECISION: "waiting for provider decision",
    PendingLaunchStage.WAITING_CLEANUP: "waiting for kill/dismiss cleanup",
    PendingLaunchStage.WAITING_LAST_LAUNCH: "waiting for the last launch to finish",
    PendingLaunchStage.SUBMITTING: "submitting",
}


@dataclass
class PendingLaunch:
    """One accepted prompt submission that has not reached the durable proc yet."""

    launch_id: str
    prompt: str
    context: PromptContext
    keep_bar: bool
    extra_payload: dict[str, object] | None
    bulk_patches: tuple[Patch, ...]
    relaunch_operation: RelaunchOperation | None
    stage: PendingLaunchStage
    placeholder_id: str | None = None
    record: LaunchRecord | None = None
    cancelled: bool = False
    submitted: bool = False
    accepted_at: float = field(default_factory=time.monotonic)
    # Stages entered through ``set_pending_launch_stage``, in order, for the
    # ``launch.submitted`` trace; ``stage`` alone is where the launch is now.
    stages_visited: list[PendingLaunchStage] = field(default_factory=list)


def begin_pending_launch(
    app: object,
    *,
    prompt: str,
    context: PromptContext,
    keep_bar: bool,
    extra_payload: dict[str, object] | None,
    bulk_patches: Sequence[Patch],
    relaunch_operation: RelaunchOperation | None,
    stage: PendingLaunchStage = PendingLaunchStage.SUBMITTING,
) -> PendingLaunch:
    """Register an accepted launch: registry entry, proc row, ``PREPARING`` record."""
    launch = PendingLaunch(
        launch_id=uuid4().hex,
        prompt=prompt,
        context=replace(context),
        keep_bar=keep_bar,
        extra_payload=dict(extra_payload) if extra_payload is not None else None,
        bulk_patches=tuple(bulk_patches),
        relaunch_operation=relaunch_operation,
        stage=stage,
    )
    _registry(app)[launch.launch_id] = launch

    display_name = (
        f"bulk {len(launch.bulk_patches)} Patches"
        if launch.bulk_patches
        else context.display_name
    )
    observer = getattr(app, "_proc_observer", None)
    register = getattr(observer, "register_pending", None)
    if callable(register):
        row = register(
            proc_type="launch",
            cl_name=context.cl_name or "",
            project_file=context.project_file,
            display_name=f"launch {display_name}",
            message=_STAGE_ROW_MESSAGES[stage],
        )
        launch.placeholder_id = row.proc_id

    launch.record = push_launch_record(
        app,
        proc_ids=(),
        prompt=prompt,
        context=replace(
            launch_record_context_from_prompt_context(context),
            display_name=display_name,
        ),
        launch_id=launch.launch_id,
    )
    if launch.record is not None:
        launch.record.relaunch_operation = relaunch_operation

    from ...util.trace import trace_event

    trace_event(
        "launch.accepted",
        launch_id=launch.launch_id,
        stage=stage.value,
        keep_bar=keep_bar,
        bulk=bool(launch.bulk_patches),
    )
    return launch


def call_pending_launch_from_worker(app: object, callback: Any, *args: Any) -> None:
    """Run *callback* on the UI thread from a pending-launch worker thread."""
    caller = getattr(app, "call_from_thread", None)
    if callable(caller):
        caller(callback, *args)
        return
    callback(*args)


def pending_launch_is_live(app: object, launch_id: str) -> bool:
    """Return whether *launch_id* is still waiting to submit (not cancelled)."""
    launch = _registry(app).get(launch_id)
    return launch is not None and not launch.cancelled


def pending_launch_for_record(
    app: object, record: LaunchRecord
) -> PendingLaunch | None:
    """Return the live pending launch behind a ``PREPARING`` *record*, if any."""
    if record.launch_id is None:
        return None
    launch = _registry(app).get(record.launch_id)
    if launch is None or launch.cancelled:
        return None
    return launch


def set_pending_launch_stage(
    app: object, launch_id: str, stage: PendingLaunchStage
) -> None:
    """Move a pending launch to *stage* and retitle its proc row to match."""
    launch = _registry(app).get(launch_id)
    if launch is None or launch.cancelled:
        return
    launch.stage = stage
    if not launch.stages_visited or launch.stages_visited[-1] is not stage:
        launch.stages_visited.append(stage)
    observer = getattr(app, "_proc_observer", None)
    update = getattr(observer, "update_pending", None)
    if callable(update) and launch.placeholder_id is not None:
        update(launch.placeholder_id, message=_STAGE_ROW_MESSAGES[stage])


def finish_pending_launch(
    app: object,
    launch: PendingLaunch,
    *,
    proc_ids: Sequence[str],
    submitted_prompts: Mapping[str, str],
) -> None:
    """Hand a submitted launch to its durable procs and retire the pending row."""
    launch.submitted = True
    _registry(app).pop(launch.launch_id, None)
    _remove_row(app, launch)
    if launch.record is not None:
        attach_launch_record_procs(
            launch.record, proc_ids=proc_ids, submitted_prompts=submitted_prompts
        )

    from ...util.trace import trace_event

    trace_event(
        "launch.submitted",
        launch_id=launch.launch_id,
        accept_to_submit_ms=round((time.monotonic() - launch.accepted_at) * 1000, 1),
        stages=[stage.value for stage in launch.stages_visited],
    )


def cancel_pending_launch(app: object, launch: PendingLaunch) -> None:
    """Withdraw a launch that never submitted: no waiter, no row, no record.

    The prompt is not restored here; callers pair this with
    :func:`restore_pending_launch_prompt` (or stash it themselves).
    """
    launch.cancelled = True
    _registry(app).pop(launch.launch_id, None)
    _remove_row(app, launch)

    from ._relaunch_barrier import drop_relaunch_cleanup_launch_waiters

    drop_relaunch_cleanup_launch_waiters(app, launch.launch_id)
    if launch.record is not None:
        discard_launch_record(app, launch.record)


def restore_pending_launch_prompt(
    app: object,
    launch: PendingLaunch,
    *,
    reason: str,
    explicit: bool,
) -> bool:
    """Give a withdrawn launch's prompt back; return whether a bar was restored.

    An *explicit* user gesture (``,X``) always restores into a prompt bar, with
    the launch's relaunch operation so a re-submit still respects any open
    barrier. An automatic abort restores only when no prompt bar is mounted and
    no modal is on the screen stack; otherwise it stashes the prompt and warns,
    so it can never overwrite a bar the user is typing in.
    """
    notify = getattr(app, "notify", None)
    if explicit or _can_restore_into_bar(app):
        ctx = launch_record_context_from_prompt_context(launch.context)
        app._edit_and_relaunch_agent(  # type: ignore[attr-defined]
            launch.prompt,
            ctx.project_file,
            ctx.cl_name,
            ctx.is_project_agent,
            relaunch_operation=launch.relaunch_operation,
        )
        if callable(notify):
            notify(f"{reason}; prompt restored")
        return True
    recover = getattr(app, "_schedule_failed_launch_prompt_recovery", None)
    if callable(recover):
        recover(launch.prompt)
    if callable(notify):
        notify(
            f"{reason}; prompt saved to stash (press @ to restore)",
            severity="warning",
        )
    return False


async def flush_pending_launch_stashes(app: object) -> None:
    """Quit-time flush: stash each still-pending prompt so ``@`` can recover it."""
    launches = [
        launch
        for launch in tuple(_registry(app).values())
        if not launch.cancelled and not launch.submitted
    ]
    if not launches:
        return
    for launch in launches:
        cancel_pending_launch(app, launch)

    from sase.history.prompt import record_failed_launch_prompt

    stashes = [
        asyncio.to_thread(
            record_failed_launch_prompt,
            launch.prompt,
            project=launch.context.project_name,
        )
        for launch in launches
    ]
    try:
        await asyncio.wait_for(
            asyncio.gather(*stashes, return_exceptions=True),
            timeout=_QUIT_STASH_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        log.warning("Timed out stashing pending launch prompts at quit")


def _can_restore_into_bar(app: object) -> bool:
    """Return whether an automatic restore may mount a prompt bar right now."""
    if not callable(getattr(app, "_edit_and_relaunch_agent", None)):
        return False
    mounted = getattr(app, "_mounted_prompt_bar", None)
    if callable(mounted) and mounted() is not None:
        return False
    from textual.screen import ModalScreen

    return not isinstance(getattr(app, "screen", None), ModalScreen)


def _remove_row(app: object, launch: PendingLaunch) -> None:
    placeholder_id, launch.placeholder_id = launch.placeholder_id, None
    if placeholder_id is None:
        return
    observer = getattr(app, "_proc_observer", None)
    remove = getattr(observer, "remove_pending", None)
    if callable(remove):
        remove(placeholder_id)


def _registry(app: object) -> dict[str, PendingLaunch]:
    registry = getattr(app, "_pending_launches", None)
    if isinstance(registry, dict):
        return registry
    registry = {}
    app._pending_launches = registry  # type: ignore[attr-defined]
    return registry


__all__ = [
    "PendingLaunch",
    "PendingLaunchStage",
    "begin_pending_launch",
    "call_pending_launch_from_worker",
    "cancel_pending_launch",
    "finish_pending_launch",
    "flush_pending_launch_stashes",
    "pending_launch_for_record",
    "pending_launch_is_live",
    "restore_pending_launch_prompt",
    "set_pending_launch_stage",
]
