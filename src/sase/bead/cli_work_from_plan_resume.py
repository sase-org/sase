"""Resume an epic that is already linked to an archived plan."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from rich.console import Console

from sase.bead.cli_work_from_plan_helpers import (
    build_work_plan,
    error_with_resume,
    ordered_agent_names,
    stale_link_message,
)
from sase.bead.cli_work_from_plan_render import render_created_beads, render_final
from sase.bead.cli_work_from_plan_types import (
    PlanFileWorkError,
    PlanFileWorkResult,
    normalize_epic_launch_result,
)
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.operation_context import BeadOperationContext
    from sase.xprompt.directive_edit import PromptWaitDirective


class _CheckpointAndPublishGraph(Protocol):
    def __call__(
        self,
        *,
        store: SddStore,
        project: BeadProject,
        epic_id: str,
        no_push: bool,
        render: bool,
    ) -> Any: ...


class _PushStoreAfterLaunch(Protocol):
    def __call__(
        self,
        store: SddStore,
        *,
        no_push: bool,
        archived_plan_path: Path | None = None,
    ) -> None: ...


class _WriteAndCommitPlanFile(Protocol):
    def __call__(
        self,
        store: SddStore,
        *,
        workspace_dir: Path,
        plan_path: Path,
        content: str,
        message: str,
    ) -> bool: ...


def resume_linked_epic(
    location: Any,
    *,
    store: SddStore,
    archived_path: Path,
    epic_id: str,
    authored_phase_ids: tuple[str, ...],
    yes: bool,
    yes_to_all: bool,
    no_push: bool,
    render: bool,
    waves: tuple[tuple[str, ...], ...],
    checkpoint_and_publish_graph: _CheckpointAndPublishGraph,
    publish_epic_rollback: Callable[[SddStore], bool],
    push_store_after_launch: _PushStoreAfterLaunch,
    timer: LaunchTimingRecorder,
    extra_waits: PromptWaitDirective | None = None,
    capacity: int | None = None,
    bead_context: BeadOperationContext | None = None,
    write_and_commit_plan_file: _WriteAndCommitPlanFile | None = None,
    workspace_dir: Path | None = None,
) -> PlanFileWorkResult:
    from sase.bead.cli_work_handler import (
        BeadWorkError,
        EpicGraphRelocatedError,
        launch_epic_bead_work,
    )

    try:
        with ExitStack() as stack:
            with timer.stage("bead_project_open"):
                project = stack.enter_context(
                    BeadProject(
                        location.root,
                        beads_dirname=location.beads_dirname,
                    )
                )
            try:
                issue = project.show(epic_id)
            except KeyError as exc:
                raise PlanFileWorkError(
                    stale_link_message(epic_id, archived_path)
                ) from exc
            if (
                issue.issue_type is not IssueType.PLAN
                or issue.tier is not BeadTier.EPIC
            ):
                raise PlanFileWorkError(
                    f"plan {archived_path} links bead_id {epic_id}, but that bead "
                    "is not an epic plan bead; remove the stale bead_id or restore "
                    "the correct bead"
                )
            phases = [
                child
                for child in project.get_epic_children(epic_id)
                if child.issue_type is IssueType.PHASE
            ]
            work_plan = build_work_plan(project, epic_id)
            if render:
                Console().print(f"[cyan]↻[/cyan] Epic bead       resuming {epic_id}")
                render_created_beads(issue, phases, work_plan, archived_path)

            def publish_resumed_graph(
                active_project: BeadProject,
                active_epic_id: str,
            ) -> Any:
                return checkpoint_and_publish_graph(
                    store=store,
                    project=active_project,
                    epic_id=active_epic_id,
                    no_push=no_push,
                    render=render,
                )

            raw_launch_result = launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=yes,
                no_push=no_push,
                yes_to_all=yes_to_all,
                defer_push=True,
                before_agent_launch=publish_resumed_graph,
                timer=timer,
                extra_waits=extra_waits,
                capacity=capacity,
                bead_context=bead_context,
            )
            launch_result = normalize_epic_launch_result(
                raw_launch_result,
                fallback_launched_agent_names=ordered_agent_names(work_plan),
            )
    except PlanFileWorkError:
        raise
    except BeadWorkError as exc:
        detail = str(exc)
        if isinstance(exc, EpicGraphRelocatedError):
            detail = _relink_resumed_plan_to_moved_epic(
                archived_path,
                exc,
                store=store,
                write_and_commit_plan_file=write_and_commit_plan_file,
                workspace_dir=workspace_dir,
                render=render,
                prior_detail=detail,
            )
        if exc.graph_published and not exc.agents_spawned:
            try:
                publish_epic_rollback(store)
            except Exception as rollback_exc:
                detail += f"; rollback publication also failed: {rollback_exc}"
        elif exc.graph_published and exc.agents_spawned:
            push_store_after_launch(
                store,
                no_push=no_push,
                archived_plan_path=archived_path,
            )
        raise error_with_resume(
            detail,
            archived_path,
            no_push=no_push and not exc.retry_requires_push,
            capacity=capacity,
        ) from exc
    except Exception as exc:
        push_store_after_launch(
            store,
            no_push=no_push,
            archived_plan_path=archived_path,
        )
        raise error_with_resume(
            str(exc),
            archived_path,
            no_push=no_push,
            capacity=capacity,
        ) from exc

    if launch_result.launched:
        push_store_after_launch(
            store,
            no_push=no_push,
            archived_plan_path=archived_path,
        )
    result = PlanFileWorkResult(
        archived_plan_path=archived_path,
        authored_phase_ids=authored_phase_ids,
        dry_run=False,
        epic_id=epic_id,
        parent_id=issue.parent_id,
        phase_bead_ids=tuple(phase.id for phase in phases),
        launched_agent_names=launch_result.launched_agent_names,
        preserved_agent_names=launch_result.preserved_agent_names,
        launch_state=launch_result.launch_state,
        launched=launch_result.launched,
        resumed=True,
        waves=waves,
        capacity=capacity,
    )
    if render:
        render_final(result)
    return result


def _relink_resumed_plan_to_moved_epic(
    archived_path: Path,
    exc: Any,
    *,
    store: SddStore,
    write_and_commit_plan_file: _WriteAndCommitPlanFile | None,
    workspace_dir: Path | None,
    render: bool,
    prior_detail: str,
) -> str:
    """Point a resumed plan at its moved epic; return the resume detail."""
    relocated_id = str(getattr(exc, "relocated_epic_id", ""))
    original_id = str(getattr(exc, "original_epic_id", ""))
    if write_and_commit_plan_file is None or workspace_dir is None:
        return (
            f"{prior_detail}; plan {archived_path} still links {original_id}; "
            f"relink bead_id to {relocated_id} and re-run "
            f"`sase bead work {archived_path}` to resume the moved epic"
        )
    from sase.sdd.frontmatter import set_frontmatter_fields

    try:
        content = archived_path.read_text(encoding="utf-8")
        updated = set_frontmatter_fields(content, {"bead_id": relocated_id})
        committed = write_and_commit_plan_file(
            store,
            workspace_dir=workspace_dir,
            plan_path=archived_path,
            content=updated,
            message=f"Relink approved epic plan to moved epic {relocated_id}",
        )
    except Exception as relink_exc:  # noqa: BLE001 - resume stays actionable
        return f"{prior_detail}; could not relink plan {archived_path} to {relocated_id}: {relink_exc}"
    if not committed:
        return (
            f"{prior_detail}; could not commit relinked plan {archived_path} "
            f"to {relocated_id}; re-running `sase bead work {archived_path}` "
            "resumes the moved epic once relinked"
        )
    if render:
        Console().print(
            f"[yellow]↻[/yellow] Plan relinked     {original_id} → {relocated_id}"
        )
    return (
        f"epic {original_id} was renumbered to {relocated_id} during "
        f"publication; plan {archived_path} relinked to {relocated_id}. "
        f"Re-running `sase bead work {archived_path}` resumes the moved epic."
    )
