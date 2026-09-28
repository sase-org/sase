"""Epic graph publication and agent launch for ``sase bead work``."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sase.bead._cli_work_handler_shared import (
    EpicWorkResult,
    ordered_selected_names,
    resume_command,
)
from sase.bead.cli_work_cleanup import rollback_work_launch
from sase.bead.cli_work_commit import (
    EpicLaunchCheckpointError,
    checkpoint_epic_work_launch,
)
from sase.bead.cli_work_handler_errors import BeadWorkError, EpicGraphRelocatedError
from sase.bead.cli_work_launch import launch_bead_work_agents
from sase.bead.cli_work_name_preflight import (
    explain_bead_work_launch_name_collision,
)
from sase.bead.project import BeadProject

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.work import PatchLaunchContext, VCSLaunchContext


def publish_epic_work_graph_and_launch(
    proj: BeadProject,
    epic_id: str,
    *,
    plan: Any,
    issue: Any,
    selection: Any,
    query: str,
    plan_snapshot: str | None,
    marked_ready_this_run: bool,
    rollback_preclaims: tuple[Any, ...],
    patch_context: PatchLaunchContext | None,
    vcs_context: VCSLaunchContext | None,
    timer: LaunchTimingRecorder,
    capacity: int | None,
    no_push: bool,
    defer_push: bool,
    before_agent_launch: Callable[[BeadProject, str], Any] | None = None,
) -> EpicWorkResult:
    """Publish the preclaimed epic graph, then launch its agents.

    This is the second half of :func:`launch_epic_bead_work`: the caller has
    completed selection, cleanup, preflight, snapshot, and preclaim. This
    helper publishes the graph, handles relocation, and spawns agents,
    returning the structured launch outcome.
    """
    from sase.bead.work import epic_work_segment_env

    graph_published = False
    graph_relocations: tuple[Any, ...] = ()
    try:
        with timer.stage("graph_publication"):
            if before_agent_launch is not None:
                callback_result = before_agent_launch(proj, epic_id)
                graph_relocations = tuple(
                    getattr(callback_result, "bead_relocations", ())
                )
            else:
                try:
                    checkpoint_result = checkpoint_epic_work_launch(
                        proj.beads_dir,
                        epic_id,
                        no_push=no_push or defer_push,
                        timer=timer,
                    )
                    graph_relocations = tuple(
                        getattr(checkpoint_result, "bead_relocations", ())
                    )
                except EpicLaunchCheckpointError as exc:
                    raise BeadWorkError(
                        str(exc),
                        preserve_epic_state=exc.checkpoint_created,
                        retry_requires_push=exc.retry_requires_push,
                    ) from exc
        graph_published = True
    except BeadWorkError as exc:
        if not exc.preserve_epic_state:
            rollback_work_launch(
                proj,
                epic_id,
                marked_ready_this_run=marked_ready_this_run,
                rollback_preclaims=rollback_preclaims,
                no_push=True,
            )
        raise
    except Exception as exc:
        rollback_work_launch(
            proj,
            epic_id,
            marked_ready_this_run=marked_ready_this_run,
            rollback_preclaims=rollback_preclaims,
            no_push=True,
        )
        raise BeadWorkError(
            f"epic graph publication failed before agent launch for {epic_id}: {exc}"
        ) from exc

    if graph_relocations:
        import dataclasses

        from sase.bead.relocation import (
            relocations_for_subtree,
            resolve_created_bead_id,
            resolve_own_bead_id,
        )

        own_relocations = relocations_for_subtree(epic_id, graph_relocations)
        try:
            moved_epic_id = resolve_own_bead_id(proj.show, issue, own_relocations)
        except ValueError as exc:
            if _pre_publication_bead_still_matches(proj, issue, epic_id):
                rollback_work_launch(
                    proj,
                    epic_id,
                    marked_ready_this_run=marked_ready_this_run,
                    rollback_preclaims=rollback_preclaims,
                    no_push=True,
                )
            raise BeadWorkError(
                f"epic graph publication relocated {epic_id} but the moved "
                f"epic could not be located: {exc}. "
                "For broader diagnostics, run `sase doctor -v`.",
                graph_published=True,
            ) from exc
        if moved_epic_id != epic_id:
            mapped_preclaims = tuple(
                dataclasses.replace(
                    prior,
                    bead_id=resolve_created_bead_id(prior.bead_id, own_relocations),
                )
                for prior in rollback_preclaims
            )
            rollback_work_launch(
                proj,
                moved_epic_id,
                marked_ready_this_run=marked_ready_this_run,
                rollback_preclaims=mapped_preclaims,
                no_push=no_push or defer_push,
            )
            raise EpicGraphRelocatedError(
                epic_id,
                moved_epic_id,
                bead_relocations=own_relocations,
            )

    try:
        with timer.stage("agent_launch"):
            with timer.stage(
                "child_segment_env",
                segment_count=len(selection.launch_names),
            ):
                segment_env = epic_work_segment_env(
                    plan,
                    plan_ref=issue.design,
                    plan_snapshot=plan_snapshot,
                    launch_names=selection.launch_names,
                )
            results = launch_bead_work_agents(
                query,
                segment_extra_env=segment_env,
                expected_names=set(selection.launch_names),
                launch_context=patch_context or vcs_context,
            )
    except Exception as e:
        launched_results = list(getattr(e, "results", []))
        launched_pids = [r.pid for r in launched_results]
        rollback_work_launch(
            proj,
            epic_id,
            marked_ready_this_run=marked_ready_this_run,
            rollback_preclaims=rollback_preclaims,
            no_push=no_push or defer_push,
            launched_pids=launched_pids,
            launched_results=launched_results,
        )
        resume = resume_command(epic_id, capacity=capacity)
        collision_detail = explain_bead_work_launch_name_collision(
            e,
            selection.launch_names,
            resume_command=resume,
            timer=timer,
        )
        detail = collision_detail if collision_detail is not None else str(e)
        raise BeadWorkError(
            f"agent launch failed for epic {epic_id}: {detail}\n"
            "For broader diagnostics, run `sase doctor -v`.",
            agents_spawned=bool(launched_results or launched_pids),
            graph_published=graph_published,
        ) from e

    agent_count = len(selection.launch_names)
    preserved_count = len(selection.preserved_names)
    preserved_text = (
        f"; preserved {preserved_count} existing" if preserved_count else ""
    )
    print(
        f"✓ Launched {agent_count} agents for epic {epic_id} — {issue.title} "
        f"(workspace {results[0].workspace_num}{preserved_text})"
    )
    return EpicWorkResult(
        epic_id=epic_id,
        launch_state="launched",
        launched_agent_names=ordered_selected_names(plan, selection.launch_names),
        preserved_agent_names=selection.preserved_names,
        workspace_num=results[0].workspace_num,
    )


def _pre_publication_bead_still_matches(
    proj: BeadProject, before: Any, bead_id: str
) -> bool:
    """Return whether ``bead_id`` still holds ``before``'s creation identity."""
    try:
        current = proj.show(bead_id)
    except (KeyError, ValueError):
        return False
    return (
        getattr(current, "issue_type", None) == getattr(before, "issue_type", None)
        and getattr(current, "title", None) == getattr(before, "title", None)
        and getattr(current, "created_at", None) == getattr(before, "created_at", None)
        and getattr(current, "created_by", None) == getattr(before, "created_by", None)
    )


__all__ = [
    "publish_epic_work_graph_and_launch",
]
