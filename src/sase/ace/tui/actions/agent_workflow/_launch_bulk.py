"""Bulk Patch fan-out for ACE agent launch submission."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from ._launch_records import LaunchRecordContext, push_launch_record
from ._launch_submit_helpers import (
    launch_record_context,
    record_submit_time_vcs_replay,
)
from ._types import PromptContext, invalidate_prompt_session

if TYPE_CHECKING:
    from sase.ace.patch import Patch
    from ...proc_observer import ObservedProc

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AcceptedBulkLaunch:
    proc: ObservedProc
    prompt: str
    context: LaunchRecordContext


class LaunchBulkSubmissionMixin:
    """Mixin submitting one durable launch per marked Patch."""

    _prompt_context: PromptContext | None
    _bulk_patches: list[Patch] | None

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
        the provider guard is dropped: each child must parse its own per-Patch
        prompt rather than replaying the unprefixed unit list.
        """
        del keep_bar
        self._bulk_patches = None
        invalidate_prompt_session(self, clear_context=False)
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
        accepted: list[AcceptedBulkLaunch] = []
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
                accepted=accepted,
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
        if accepted:
            context = accepted[0].context
            if len(accepted) > 1:
                context = LaunchRecordContext(
                    display_name=f"bulk {len(accepted)} Patches",
                    project_file=context.project_file,
                    cl_name=context.cl_name,
                    is_project_agent=context.is_project_agent,
                )
            push_launch_record(
                self,
                proc_ids=tuple(slot.proc.proc_id for slot in accepted),
                prompt=prompt,
                context=context,
                submitted_prompts={slot.proc.proc_id: slot.prompt for slot in accepted},
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
        accepted: list[AcceptedBulkLaunch] | None = None,
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
                return False

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
        proc_info = self._submit_launch_proc(  # type: ignore[attr-defined]
            display_name=f"launch {display_name}",
            cl_name=cl_name,
            project_file=project_file,
            prompt=cl_prompt,
            dedup_key=f"launch:{workflow_name}",
            extra_payload=payload,
            submitted_prompt=cl_prompt,
        )
        if proc_info is not None:
            if accepted is not None:
                accepted.append(
                    AcceptedBulkLaunch(
                        proc=proc_info,
                        prompt=cl_prompt,
                        context=launch_record_context(
                            display_name=display_name,
                            project_file=project_file,
                            cl_name=cl_name,
                        ),
                    )
                )
            record_submit_time_vcs_replay(cl_prompt)
        return proc_info is not None

    def _clear_bulk_patch_marks(self) -> None:
        """Drop Patch marks after a bulk submit so the UI matches reality."""
        targets = getattr(self, "_artifacts_marked_targets", None)
        if isinstance(targets, dict):
            targets["patches"] = set()
        refresh = getattr(self, "_refresh_display", None)
        if callable(refresh):
            refresh()


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
