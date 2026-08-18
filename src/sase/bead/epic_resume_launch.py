"""Detached host-side launch helpers for resuming a stalled epic."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.bead.epic_launch import (
    EpicLaunchOrigin,
    epic_launch_origin_from_gate_source,
)

if TYPE_CHECKING:
    from sase.procs.models import Proc


_EPIC_RESUME_TAGS = ("epic", "resume")
_EPIC_RESUME_SUBMIT_LOCK = "epic-resume-submit"
_EPIC_RESUME_LEASE_WORKFLOW = "epic-resume"

type EpicResumeOrigin = EpicLaunchOrigin


def epic_resume_origin_from_gate_source(
    source: str | None,
) -> EpicResumeOrigin:
    """Map a neutral gate response source to its epic-resume origin."""
    return epic_launch_origin_from_gate_source(source)


def build_epic_resume_argv(epic_id: str) -> list[str]:
    """Build the canonical detached epic-resume launch command."""
    return ["sase", "bead", "work", epic_id, "--yes-to-all"]


def submit_epic_resume_task(
    epic_id: str,
    *,
    project: str,
    origin: EpicResumeOrigin = "api",
) -> Proc:
    """Submit or reuse one detached epic-resume launch through a leased checkout."""
    from sase.logs._bounded import log_file_lock
    from sase.procs import procs_dir
    from sase.procs.request import ProcSubmitRequest
    from sase.workspace_provider.lease import (
        acquire_operational_lease,
        submit_via_lease,
    )

    with log_file_lock(procs_dir() / _EPIC_RESUME_SUBMIT_LOCK):
        if existing := active_epic_resume(epic_id):
            return existing
        lease = acquire_operational_lease(
            project,
            workflow=_EPIC_RESUME_LEASE_WORKFLOW,
            holder=f"epic-resume:{epic_id}",
        )
        return submit_via_lease(
            ProcSubmitRequest(
                argv=build_epic_resume_argv(epic_id),
                label=f"Epic resume · {epic_id}",
                cwd=str(lease.checkout_dir),
                origin=origin,
                project=project,
                session_id=None,
                tags=_EPIC_RESUME_TAGS,
            ),
            lease,
        )


def _is_epic_resume_row(task: Proc) -> bool:
    """Return whether *task* is a detached epic-resume launch row."""
    return set(_EPIC_RESUME_TAGS).issubset(task.tags) and (
        len(task.command) >= 4 and task.command[:3] == ["sase", "bead", "work"]
    )


def active_epic_resume(epic_id: str) -> Proc | None:
    """Return the newest active resume launch for *epic_id*, if any."""
    from sase.procs import (
        ACTIVE_PROC_STATUSES,
        COMMAND_PROC_KIND,
        DETACHED_PROC_KIND,
        read_procs,
    )

    for task in read_procs(
        status=ACTIVE_PROC_STATUSES,
        kind={COMMAND_PROC_KIND, DETACHED_PROC_KIND},
    ):
        if _is_epic_resume_row(task) and task.command[3] == epic_id:
            return task
    return None


__all__ = [
    "EpicResumeOrigin",
    "active_epic_resume",
    "build_epic_resume_argv",
    "epic_resume_origin_from_gate_source",
    "submit_epic_resume_task",
]
