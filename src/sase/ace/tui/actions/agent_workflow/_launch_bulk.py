"""Bulk Patch fan-out for ACE agent launch submission."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from ._launch_records import LaunchRecordContext
from ._launch_submit_helpers import (
    launch_record_context,
    schedule_submit_time_vcs_replay,
)
from ._pending_launch import (
    PendingLaunch,
    call_pending_launch_from_worker,
    cancel_pending_launch,
    finish_pending_launch,
    pending_launch_is_live,
    restore_pending_launch_prompt,
)
from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.patch import Patch
    from ...proc_observer import ObservedProc

log = logging.getLogger(__name__)

_BULK_RESOLVE_GROUP = "launch-bulk-resolve"


@dataclass(frozen=True)
class AcceptedBulkLaunch:
    proc: ObservedProc
    prompt: str
    context: LaunchRecordContext


@dataclass(frozen=True)
class _BulkPatchPlan:
    """One marked Patch's resolved launch, ready for the UI thread to submit."""

    cl_name: str
    project_name: str
    project_file: str
    prompt: str
    display_name: str
    workflow_name: str
    payload: dict[str, object]


@dataclass(frozen=True)
class _BulkLaunchPlan:
    """Per-Patch launch plans in Patch order; ``None`` marks a Patch that failed."""

    slots: tuple[_BulkPatchPlan | None, ...]
    first_timestamp: str


class LaunchBulkSubmissionMixin:
    """Mixin submitting one durable launch per marked Patch."""

    _prompt_context: PromptContext | None
    _bulk_patches: list[Patch] | None

    def _submit_bulk_pending_launch(self, launch: PendingLaunch) -> None:
        """Fan a bulk pending launch out to one durable ``sase run`` per Patch.

        The shared prompt is rewritten with each Patch's VCS prefix so every
        launch carries that Patch's project/cl context. ``launch_units`` from
        the provider guard is dropped: each child must parse its own per-Patch
        prompt rather than replaying the unprefixed unit list.

        Project-file resolution, workflow detection, and prompt rewriting read
        the disk, so they run in a thread worker that returns a typed per-Patch
        plan; the UI thread then submits the procs and pushes the record.
        """
        from ...util.trace import set_trace_context

        n = len(launch.bulk_patches)
        set_trace_context(
            last_action="launch",
            last_action_display_name=f"bulk {n} Patches",
        )
        self.notify(f"Launching {n} agent(s)...")  # type: ignore[attr-defined]

        shared_extra = {
            key: value
            for key, value in dict(launch.extra_payload or {}).items()
            if key != "launch_units"
        }

        def resolve() -> None:
            try:
                plan = _plan_bulk_launch(
                    launch.prompt, launch.bulk_patches, shared_extra
                )
            except Exception:
                log.warning("bulk launch planning failed", exc_info=True)
                plan = None
            call_pending_launch_from_worker(
                self, self._finish_bulk_pending_launch, launch, plan
            )

        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            resolve()
            return
        # Non-exclusive: a second launch must not cancel this launch's plan.
        run_worker(
            resolve,
            thread=True,
            group=f"{_BULK_RESOLVE_GROUP}-{launch.launch_id}",
        )

    def _finish_bulk_pending_launch(
        self, launch: PendingLaunch, plan: _BulkLaunchPlan | None
    ) -> None:
        """UI-thread half of the bulk fan-out: submit each planned Patch."""
        if not pending_launch_is_live(self, launch.launch_id):
            log.debug("Dropping bulk plan for cancelled pending launch")
            return
        if plan is None:
            self._abort_bulk_pending_launch(launch, "Bulk launch failed")
            return

        from ...util.trace import set_trace_context

        set_trace_context(last_action_ts=plan.first_timestamp)

        launched = 0
        failed = 0
        accepted: list[AcceptedBulkLaunch] = []
        for slot in plan.slots:
            if slot is not None and self._submit_bulk_patch_plan(slot, accepted):
                launched += 1
            else:
                failed += 1

        if failed:
            self.notify(  # type: ignore[attr-defined]
                f"Started {launched} agent(s), {failed} failed",
                severity="warning",
            )
        if not accepted:
            self._abort_bulk_pending_launch(launch, "No agent was launched")
            return

        context = accepted[0].context
        if len(accepted) > 1:
            context = LaunchRecordContext(
                display_name=f"bulk {len(accepted)} Patches",
                project_file=context.project_file,
                cl_name=context.cl_name,
                is_project_agent=context.is_project_agent,
            )
        if launch.record is not None:
            launch.record.context = context
        finish_pending_launch(
            self,
            launch,
            proc_ids=tuple(slot.proc.proc_id for slot in accepted),
            submitted_prompts={slot.proc.proc_id: slot.prompt for slot in accepted},
        )
        schedule_submit_time_vcs_replay(self, [slot.prompt for slot in accepted])

    def _abort_bulk_pending_launch(self, launch: PendingLaunch, reason: str) -> None:
        """Withdraw a bulk launch that submitted nothing and return its prompt."""
        cancel_pending_launch(self, launch)
        restore_pending_launch_prompt(self, launch, reason=reason, explicit=False)

    def _submit_bulk_patch_plan(
        self,
        plan: _BulkPatchPlan,
        accepted: list[AcceptedBulkLaunch],
    ) -> bool:
        """Submit one planned marked-Patch launch. Return whether it was accepted."""
        proc_info = self._submit_launch_proc(  # type: ignore[attr-defined]
            display_name=f"launch {plan.display_name}",
            cl_name=plan.cl_name,
            project_file=plan.project_file,
            prompt=plan.prompt,
            dedup_key=f"launch:{plan.workflow_name}",
            extra_payload=dict(plan.payload),
            submitted_prompt=plan.prompt,
        )
        if proc_info is None:
            return False
        accepted.append(
            AcceptedBulkLaunch(
                proc=proc_info,
                prompt=plan.prompt,
                context=launch_record_context(
                    display_name=plan.display_name,
                    project_file=plan.project_file,
                    cl_name=plan.cl_name,
                ),
            )
        )
        return True

    def _clear_bulk_patch_marks(self) -> None:
        """Drop Patch marks after a bulk submit so the UI matches reality."""
        targets = getattr(self, "_artifacts_marked_targets", None)
        if isinstance(targets, dict):
            targets["patches"] = set()
        refresh = getattr(self, "_refresh_display", None)
        if callable(refresh):
            refresh()


def _plan_bulk_launch(
    prompt: str,
    patches: tuple[Patch, ...],
    extra_payload: dict[str, object],
) -> _BulkLaunchPlan:
    """Resolve every marked Patch's launch off the UI thread.

    Reserves one timestamp per Patch, resolves each Patch's project file and
    workflow type, and rewrites the shared prompt with the Patch's VCS prefix.
    A Patch that cannot be resolved is logged durably and planned as ``None``.
    """
    from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

    count = len(patches)
    timestamps = reserve_launch_timestamp_batch(count)
    slots = tuple(
        _plan_one_bulk_patch(
            prompt,
            patch,
            timestamp=timestamps[index],
            extra_payload=extra_payload,
            slot_index=index,
            slot_count=count,
        )
        for index, patch in enumerate(patches)
    )
    return _BulkLaunchPlan(slots=slots, first_timestamp=timestamps[0])


def _plan_one_bulk_patch(
    prompt: str,
    patch: Patch,
    *,
    timestamp: str,
    extra_payload: dict[str, object],
    slot_index: int,
    slot_count: int,
) -> _BulkPatchPlan | None:
    """Plan one marked-Patch launch, or ``None`` when it cannot be resolved."""
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
            log_bulk_item_failure(
                FileNotFoundError(f"No project file for {cl_name}"),
                cl_name=cl_name,
                project_name=project_name,
                prompt=prompt,
                slot_index=slot_index,
                slot_count=slot_count,
                stage="project_file",
                project_file=project_file or "",
            )
            return None

    try:
        workflow_type = detect_workflow_type(project_file)
    except Exception as exc:
        log_bulk_item_failure(
            exc,
            cl_name=cl_name,
            project_name=project_name,
            prompt=prompt,
            slot_index=slot_index,
            slot_count=slot_count,
            stage="workflow_type",
            project_file=project_file,
        )
        return None

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
    return _BulkPatchPlan(
        cl_name=cl_name,
        project_name=project_name,
        project_file=project_file,
        prompt=cl_prompt,
        display_name=display_name,
        workflow_name=workflow_name,
        payload=payload,
    )


def log_bulk_item_failure(
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


__all__ = [
    "AcceptedBulkLaunch",
    "LaunchBulkSubmissionMixin",
    "log_bulk_item_failure",
]
