"""Shared plan-file launch operations used by private launch modules."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from sase.bead.cli_work_from_plan_hooks import PlanFileWorkLaunchHooks
from sase.bead.cli_work_from_plan_resume import (
    resume_linked_epic as resume_linked_epic_impl,
)
from sase.bead.cli_work_from_plan_types import PlanFileWorkResult
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.operation_context import BeadOperationContext
    from sase.macro.directive_edit import PromptWaitDirective


def resume_linked_epic(
    location: Any,
    *,
    hooks: PlanFileWorkLaunchHooks,
    store: SddStore,
    workspace_dir: Path,
    archived_path: Path,
    epic_id: str,
    authored_phase_ids: tuple[str, ...],
    bead_context: BeadOperationContext | None,
    yes: bool,
    yes_to_all: bool,
    no_push: bool,
    render: bool,
    waves: tuple[tuple[str, ...], ...],
    timer: LaunchTimingRecorder,
    extra_waits: PromptWaitDirective | None = None,
    capacity: int | None = None,
    creator_artifacts_dir: Path | str | None = None,
    creator_via: str | None = None,
) -> PlanFileWorkResult:
    from sase.sdd.plan_refs import plan_ref_for_store

    return resume_linked_epic_impl(
        location,
        store=store,
        archived_path=archived_path,
        epic_id=epic_id,
        authored_phase_ids=authored_phase_ids,
        yes=yes,
        yes_to_all=yes_to_all,
        no_push=no_push,
        render=render,
        waves=waves,
        checkpoint_and_publish_graph=hooks.checkpoint_and_publish_graph,
        publish_epic_rollback=hooks.publish_epic_rollback,
        push_store_after_launch=hooks.push_store_after_launch,
        timer=timer,
        extra_waits=extra_waits,
        capacity=capacity,
        bead_context=bead_context,
        write_and_commit_plan_file=hooks.write_and_commit_plan_file,
        workspace_dir=workspace_dir,
        creator_artifacts_dir=creator_artifacts_dir,
        creator_via=creator_via,
        creator_project=_creator_entry_project(store, bead_context, workspace_dir),
        creator_plan_ref=plan_ref_for_store(
            archived_path,
            store,
            workspace_dir=workspace_dir,
        ),
    )


def _creator_entry_project(
    store: SddStore,
    bead_context: BeadOperationContext | None,
    workspace_dir: Path,
) -> str | None:
    """Return the best-effort project identity for a created-epic entry."""
    for candidate in (
        getattr(bead_context, "project_key", None),
        getattr(store, "project_key", None),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    try:
        from sase.bead.epic_launch import resolve_epic_launch_project

        return resolve_epic_launch_project(workspace_dir)
    except Exception:
        return None


def record_created_epic(
    creator_artifacts_dir: Path | str | None,
    creator_via: str | None,
    *,
    epic_id: str,
    store: SddStore,
    bead_context: BeadOperationContext | None,
    workspace_dir: Path,
    plan_ref: str | None,
) -> None:
    """Best-effort authoritative record of one created epic; never raises."""
    if creator_artifacts_dir is None:
        return
    from sase.core.created_epics import HOST_LAUNCH_VIA, record_created_epic

    record_created_epic(
        creator_artifacts_dir,
        bead_id=epic_id,
        project=_creator_entry_project(store, bead_context, workspace_dir),
        plan_ref=plan_ref,
        via=creator_via or HOST_LAUNCH_VIA,
    )


def checkpoint_and_publish_graph(
    *,
    hooks: PlanFileWorkLaunchHooks,
    store: SddStore,
    project: BeadProject,
    epic_id: str,
    no_push: bool,
    render: bool,
) -> Any:
    """Commit the complete ready graph and cross the visibility barrier."""
    from sase.bead.cli_work_handler import BeadWorkError
    from sase.bead.cli_work_handler_errors import EpicGraphPublicationConflictError
    from sase.bead.sync import bead_state_is_clean, commit_epic_graph_checkpoint

    try:
        hooks.require_plan_store_health(store)
        commit_epic_graph_checkpoint(project.beads_dir, epic_id)
        if not bead_state_is_clean(project.beads_dir):
            raise RuntimeError("bead-state changes remain uncommitted")
    except Exception as exc:
        raise BeadWorkError(
            f"epic graph commit failed before agent launch for {epic_id}: {exc}"
        ) from exc
    if render:
        Console().print(
            f"[green]✓[/green] Graph committed epic {epic_id} · workers preassigned"
        )
    # The checkpoint commit is this attempt's first recorded beads-repo
    # commit; the replay safety check compares it against the unpublished
    # range before discarding anything.
    from sase.bead.sync import bead_store_head_sha

    checkpoint_sha = bead_store_head_sha(project.beads_dir)

    try:
        published = hooks.publish_epic_graph_before_launch(store, no_push=no_push)
    except EpicGraphPublicationConflictError as exc:
        if exc.checkpoint_sha is None:
            exc.checkpoint_sha = checkpoint_sha
        raise
    except Exception as exc:
        raise BeadWorkError(
            f"epic graph publication failed before agent launch for {epic_id}: {exc}",
            preserve_epic_state=True,
            retry_requires_push=no_push,
        ) from exc
    if render:
        destination = "remote" if published else "shared authoritative store"
        Console().print(f"[green]✓[/green] Graph published {epic_id} · {destination}")
    return published
