"""Launch and resume transactions for plan-file bead work."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from rich.console import Console

from sase.bead.cli_work_from_plan_helpers import (
    build_work_plan,
    error_with_resume,
    linked_bead_id_if_present,
    linked_epic_belongs_to_other_plan,
    ordered_agent_names,
    require_matching_plan_identity,
    require_parent_override_matches_linked,
    resolve_linked_epic,
    same_path,
)
from sase.bead.cli_work_from_plan_hooks import PlanFileWorkLaunchHooks
from sase.bead.cli_work_from_plan_render import (
    render_created_beads,
    render_final,
    render_stale_link_replacement,
)
from sase.bead.cli_work_from_plan_resume import (
    resume_linked_epic as _resume_linked_epic_impl,
)
from sase.bead.cli_work_from_plan_types import (
    PlanFileWorkError,
    PlanFileWorkResult,
    normalize_epic_launch_result,
)
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.operation_context import BeadOperationContext
    from sase.macro.directive_edit import PromptWaitDirective

_EPIC_CREATION_MAX_ATTEMPTS = 3


def work_from_plan_file_locked(
    *,
    hooks: PlanFileWorkLaunchHooks,
    location: Any,
    store: SddStore,
    workspace_dir: Path,
    source_path: Path,
    destination_name: str | None,
    plan: Any,
    phase_ids: tuple[str, ...],
    waves: tuple[tuple[str, ...], ...],
    parent_id: str | None,
    parent: str | None,
    bead_context: BeadOperationContext | None,
    yes: bool,
    yes_to_all: bool,
    no_push: bool,
    render: bool,
    expect_prompt_snapshot: bool = False,
    timer: LaunchTimingRecorder,
    extra_waits: PromptWaitDirective | None = None,
    capacity: int | None = None,
    creator_artifacts_dir: Path | str | None = None,
    creator_via: str | None = None,
) -> PlanFileWorkResult:
    """Run one mutation transaction while its store launch lock is held."""
    from sase.bead.cli_work_handler import preload_launch_imports
    from sase.sdd.plan_archive import archive_plan_file

    preload_launch_imports(timer)

    try:
        with timer.stage("plan_store_health_pre_archive"):
            hooks.require_plan_store_health(store)
    except Exception as exc:
        raise error_with_resume(
            f"approved epic plans store is not safe to use: {exc}",
            source_path,
            no_push=no_push,
            capacity=capacity,
        ) from exc

    try:
        with timer.stage("archive_plan_file"):
            archive_result = archive_plan_file(
                source_path,
                store,
                tier="epic",
                destination_name=destination_name,
                preserve_existing=True,
                primary_root=workspace_dir,
                expect_prompt_snapshot=expect_prompt_snapshot,
            )
    except Exception as exc:
        raise error_with_resume(
            f"could not archive epic plan {source_path}: {exc}",
            source_path,
            no_push=no_push,
            capacity=capacity,
        ) from exc
    archived_path = archive_result.path
    if not archive_result.written and not same_path(source_path, archived_path):
        require_matching_plan_identity(
            source_path,
            source_title=plan.title,
            archived_path=archived_path,
            no_push=no_push,
            capacity=capacity,
        )
    with timer.stage("archived_plan_commit", written=archive_result.written):
        from sase._plan_archive_approval import archive_commit_paths

        archive_committed = not archive_result.written or hooks.commit_plan_file(
            store,
            workspace_dir=workspace_dir,
            plan_path=archived_path,
            message=f"Archive approved plan {archived_path.stem}",
            paths=archive_commit_paths(archived_path),
        )
    if not archive_committed:
        raise error_with_resume(
            f"failed to commit archived epic plan {archived_path}",
            archived_path,
            no_push=no_push,
            capacity=capacity,
        )
    if render:
        detail = "committed" if archive_result.written else "already archived"
        Console().print(f"[green]✓[/green] Archived        {archived_path} ({detail})")

    try:
        with timer.stage("plan_store_health_post_archive"):
            hooks.require_plan_store_health(store)
    except Exception as exc:
        raise error_with_resume(
            f"approved epic plans store is not safe to use: {exc}",
            source_path,
            no_push=no_push,
            capacity=capacity,
        ) from exc

    from sase.bead.cli_work_from_plan_premint import refresh_store_before_epic_mint
    from sase.sdd.plan_refs import plan_ref_for_store

    plan_ref = plan_ref_for_store(
        archived_path,
        store,
        workspace_dir=workspace_dir,
    )
    refresh_store_before_epic_mint(
        beads_dir=location.beads_dir,
        archived_path=archived_path,
        no_push=no_push,
        capacity=capacity,
        render=render,
        parent=parent,
        timer=timer,
    )

    linked_epic_id = linked_bead_id_if_present(archived_path)
    stale_epic_id: str | None = None
    if linked_epic_id is not None:
        from sase.bead.epic_from_plan import require_epic_parent

        linked_issue = resolve_linked_epic(
            location,
            linked_epic_id,
            archived_path,
        )
        if linked_issue is not None and not linked_epic_belongs_to_other_plan(
            linked_issue,
            archived_path=archived_path,
            store=store,
            workspace_dir=workspace_dir,
        ):
            timer.fields["bead_id"] = linked_issue.id
            if parent_id is not None:
                with ExitStack() as stack:
                    with timer.stage("bead_project_open"):
                        project = stack.enter_context(
                            BeadProject(
                                location.root,
                                beads_dirname=location.beads_dirname,
                            )
                        )
                    parent_issue = require_epic_parent(
                        project, parent_id, plan_path=archived_path
                    )
                    if parent_issue is not None:
                        parent_id = parent_issue.id
            require_parent_override_matches_linked(
                linked_issue,
                parent_id,
                parent_override=parent,
                plan_path=archived_path,
            )
            return resume_linked_epic(
                location,
                hooks=hooks,
                store=store,
                workspace_dir=workspace_dir,
                archived_path=archived_path,
                epic_id=linked_issue.id,
                authored_phase_ids=phase_ids,
                bead_context=bead_context,
                yes=yes,
                yes_to_all=yes_to_all,
                no_push=no_push,
                render=render,
                waves=waves,
                timer=timer,
                extra_waits=extra_waits,
                capacity=capacity,
                creator_artifacts_dir=creator_artifacts_dir,
                creator_via=creator_via,
            )
        stale_epic_id = linked_epic_id
        if render:
            foreign_title = None
            foreign_plan_ref = None
            if linked_issue is not None:
                foreign_title = linked_issue.title
                foreign_plan_ref = linked_issue.design.strip() or None
            render_stale_link_replacement(
                stale_epic_id,
                archived_path,
                dry_run=False,
                foreign_title=foreign_title,
                foreign_plan_ref=foreign_plan_ref,
            )

    from sase.bead.cli_work_handler import launch_epic_bead_work
    from sase.bead.epic_from_plan import (
        EpicFromPlanError,
        create_and_launch_epic_from_plan,
    )

    launched_names: tuple[str, ...] = ()
    preserved_names: tuple[str, ...] = ()
    launch_state = ""
    attempted_epic_ids: list[str] = []

    def commit_plan_link(path: Path, content: str, message: str) -> bool:
        return hooks.write_and_commit_plan_file(
            store,
            workspace_dir=workspace_dir,
            plan_path=path,
            content=content,
            message=message,
        )

    def publish_created_graph(project: BeadProject, epic_id: str) -> Any:
        from sase.bead.cli_work_handler_errors import EpicGraphPublicationConflictError
        from sase.bead.sync import bead_store_head_sha

        try:
            return hooks.checkpoint_and_publish_graph(
                store=store,
                project=project,
                epic_id=epic_id,
                no_push=no_push,
                render=render,
            )
        except EpicGraphPublicationConflictError as exc:
            # Record the attempt's tip as a fallback. The launch handler
            # overwrites this with the post-rollback HEAD after its own
            # rollback runs; without a handler rollback this is the tip.
            if exc.attempt_tip_sha is None:
                exc.attempt_tip_sha = bead_store_head_sha(project.beads_dir)
            raise

    def launch_created_epic(project: BeadProject, epic_id: str) -> bool:
        nonlocal launched_names, preserved_names, launch_state
        attempted_epic_ids.append(epic_id)
        issue = project.show(epic_id)
        phases = [
            child
            for child in project.get_epic_children(epic_id)
            if child.issue_type is IssueType.PHASE
        ]
        work_plan = build_work_plan(project, epic_id)
        launched_names = ordered_agent_names(work_plan)
        if render:
            render_created_beads(issue, phases, work_plan, archived_path)
        raw_result = launch_epic_bead_work(
            project,
            epic_id,
            dry_run=False,
            yes=yes,
            no_push=no_push,
            yes_to_all=yes_to_all,
            defer_push=True,
            before_agent_launch=publish_created_graph,
            timer=timer,
            extra_waits=extra_waits,
            capacity=capacity,
            bead_context=bead_context,
        )
        result = normalize_epic_launch_result(
            raw_result,
            fallback_launched_agent_names=ordered_agent_names(work_plan),
        )
        launched_names = result.launched_agent_names
        preserved_names = result.preserved_agent_names
        launch_state = result.launch_state
        return result.launched

    timer.fields["relocation_retries"] = 0
    relocation_retries = 0
    timer.fields["publication_conflict_replays"] = 0
    publication_conflict_replays = 0
    created: Any = None
    try:
        for attempt in range(1, _EPIC_CREATION_MAX_ATTEMPTS + 1):
            launched_names = ()
            preserved_names = ()
            launch_state = ""
            launch_base = refresh_store_before_epic_mint(
                beads_dir=location.beads_dir,
                archived_path=archived_path,
                no_push=no_push,
                capacity=capacity,
                render=render,
                parent=parent,
                timer=timer,
            )
            timer.fields["launch_base"] = launch_base
            try:
                with ExitStack() as stack:
                    with timer.stage("bead_project_open"):
                        project = stack.enter_context(
                            BeadProject(
                                location.root,
                                beads_dirname=location.beads_dirname,
                            )
                        )
                    created = create_and_launch_epic_from_plan(
                        project,
                        plan_path=archived_path,
                        plan_ref=plan_ref,
                        commit_plan_update=commit_plan_link,
                        launch_work=launch_created_epic,
                        parent_override=parent,
                        replace_stale_bead_id=stale_epic_id,
                        store=store,
                        primary_root=workspace_dir,
                        expect_prompt_snapshot=expect_prompt_snapshot,
                        timer=timer,
                    )
                    timer.fields["bead_id"] = created.epic.id
                    break
            except EpicFromPlanError as retry_exc:
                if retry_exc.publication_conflict:
                    if attempt >= _EPIC_CREATION_MAX_ATTEMPTS:
                        raise
                    recovery_ref = _replay_publication_conflict(
                        beads_dir=location.beads_dir,
                        launch_base=launch_base,
                        epic_id=attempted_epic_ids[-1] if attempted_epic_ids else "?",
                        checkpoint_sha=retry_exc.checkpoint_sha,
                        attempt_tip_sha=retry_exc.attempt_tip_sha,
                        cause=str(retry_exc),
                        archived_path=archived_path,
                    )
                    publication_conflict_replays += 1
                    timer.fields["publication_conflict_replays"] = (
                        publication_conflict_replays
                    )
                    if render:
                        old_id = attempted_epic_ids[-1] if attempted_epic_ids else "?"
                        Console().print(
                            f"[yellow]↻[/yellow] Epic ID {old_id} could not be "
                            "merged with concurrently published history; "
                            "discarded the unpublished launch graph "
                            f"(recovery ref {recovery_ref}), retrying "
                            f"(attempt {attempt + 1}/{_EPIC_CREATION_MAX_ATTEMPTS})"
                        )
                    # The store is back at upstream and the next attempt
                    # re-runs the pre-mint refresh, opens a fresh
                    # BeadProject, and mints a fresh ID. stale_epic_id stays
                    # unchanged: the plan link was restored to its original
                    # content before the replay.
                    continue
                relocated_id = retry_exc.relocated_epic_id
                rollback_clean = "; rollback also failed" not in str(retry_exc)
                if (
                    relocated_id is None
                    or not rollback_clean
                    or attempt >= _EPIC_CREATION_MAX_ATTEMPTS
                ):
                    raise
                try:
                    hooks.publish_epic_rollback(store)
                except Exception as publish_exc:
                    # The rollback is committed locally but unpublished, so do
                    # not retry; keep the relocation detail in the resume error.
                    raise EpicFromPlanError(
                        f"{retry_exc}; rollback publication also failed: {publish_exc}",
                        graph_published=True,
                        retry_requires_push=retry_exc.retry_requires_push,
                        relocated_epic_id=relocated_id,
                    ) from publish_exc
                relocation_retries += 1
                timer.fields["relocation_retries"] = relocation_retries
                if render:
                    old_id = attempted_epic_ids[-1] if attempted_epic_ids else "?"
                    Console().print(
                        f"[yellow]↻[/yellow] Epic ID {old_id} "
                        f"collided with a concurrently published bead "
                        f"(moved to {relocated_id}); rolled back, "
                        f"retrying (attempt {attempt + 1}/{_EPIC_CREATION_MAX_ATTEMPTS})"
                    )
                # The conflict resolver advances the store's next_counter
                # past every relocation and stream ID (even when config.json
                # itself merged cleanly), so the retry mints fresh IDs.
                # stale_epic_id stays unchanged: rollback restored the
                # original plan content.
                continue
    except PlanFileWorkError:
        raise
    except Exception as exc:
        retry_requires_push = False
        detail = str(exc)
        if isinstance(exc, EpicFromPlanError):
            retry_requires_push = exc.retry_requires_push
            if exc.graph_published and exc.rollback_performed:
                try:
                    hooks.publish_epic_rollback(store)
                    if render:
                        Console().print(
                            "[yellow]↺[/yellow] Rollback published "
                            "after zero-spawn launch failure"
                        )
                except Exception as rollback_exc:
                    detail += f"; rollback publication also failed: {rollback_exc}"
            elif exc.graph_published and exc.state_preserved:
                if attempted_epic_ids:
                    _record_created_epic(
                        creator_artifacts_dir,
                        creator_via,
                        epic_id=attempted_epic_ids[-1],
                        store=store,
                        bead_context=bead_context,
                        workspace_dir=workspace_dir,
                        plan_ref=plan_ref,
                    )
                hooks.push_store_after_launch(
                    store,
                    no_push=no_push,
                    archived_plan_path=archived_path,
                )
        raise error_with_resume(
            detail,
            archived_path,
            no_push=no_push and not retry_requires_push,
            parent_override=parent,
            capacity=capacity,
        ) from exc

    assert created is not None
    _record_created_epic(
        creator_artifacts_dir,
        creator_via,
        epic_id=created.epic.id,
        store=store,
        bead_context=bead_context,
        workspace_dir=workspace_dir,
        plan_ref=plan_ref,
    )
    hooks.push_store_after_launch(
        store,
        no_push=no_push,
        archived_plan_path=archived_path,
    )

    result = PlanFileWorkResult(
        archived_plan_path=archived_path,
        authored_phase_ids=phase_ids,
        dry_run=False,
        epic_id=created.epic.id,
        parent_id=created.epic.parent_id,
        replaced_stale_epic_id=stale_epic_id,
        phase_bead_ids=tuple(phase.id for phase in created.phases),
        launched_agent_names=launched_names,
        preserved_agent_names=preserved_names,
        launch_state=launch_state,
        launched=True,
        resumed=False,
        waves=waves,
        capacity=capacity,
    )
    if render:
        render_final(result)
    return result


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

    return _resume_linked_epic_impl(
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


def _record_created_epic(
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


def _replay_publication_conflict(
    *,
    beads_dir: Path,
    launch_base: str | None,
    epic_id: str,
    checkpoint_sha: str | None,
    attempt_tip_sha: str | None,
    cause: str,
    archived_path: Path,
) -> str:
    """Discard this attempt's unpublished graph; return the recovery ref.

    Raises :class:`EpicFromPlanError` with manual recovery steps when any
    safety check fails; the caller must not reset then.
    """
    from sase.bead.epic_from_plan import EpicFromPlanError
    from sase.bead.sync import bead_store_git_root

    def _refuse(reason: str) -> NoReturn:
        raise EpicFromPlanError(
            _publication_replay_refusal_message(
                cause=cause,
                epic_id=epic_id,
                beads_dir=beads_dir,
                archived_path=archived_path,
                reason=reason,
            ),
            publication_conflict=True,
        )

    repo_root = bead_store_git_root(beads_dir)
    if repo_root is None:
        _refuse(f"could not locate the beads git repo for {beads_dir}")

    try:
        from sase.workspace_provider.ownership import authorize_store_mutation

        authorize_store_mutation(repo_root)
    except Exception as exc:
        _refuse(f"the workspace ownership guard refused the reset: {exc}")

    import subprocess

    from sase.sdd._git import run_sdd_git
    from sase.sdd._git_contention import store_git_write_lock

    def _git(args: list[str], op: str) -> subprocess.CompletedProcess[Any]:
        return run_sdd_git(
            args,
            cwd=repo_root,
            op=op,
            check=False,
            capture_output=True,
            text=True,
        )

    with store_git_write_lock(
        repo_root,
        op="bead.publication_conflict_replay",
        mutates_worktree=True,
    ) as acquired:
        if not acquired:
            _refuse(
                "could not acquire the beads store write lock; another writer holds it"
            )
        fetched = _git(["fetch"], "bead.publication_conflict_replay.fetch")
        if fetched.returncode != 0:
            _refuse(
                "could not fetch the beads repo: "
                f"{(fetched.stderr or fetched.stdout or '').strip()}"
            )
        upstream = _git(
            ["rev-parse", "--verify", "@{upstream}"],
            "bead.publication_conflict_replay.upstream",
        )
        if upstream.returncode != 0 or not upstream.stdout.strip():
            _refuse("the beads clone has no configured upstream to reset to")
        upstream_sha = upstream.stdout.strip()

        if not launch_base:
            _refuse("no launch base was recorded before minting this attempt")
        ancestor = _git(
            ["merge-base", "--is-ancestor", launch_base, "@{upstream}"],
            "bead.publication_conflict_replay.ancestor",
        )
        if ancestor.returncode != 0:
            _refuse(
                f"the launch base {launch_base} is not an ancestor of "
                "@{upstream}; another writer moved the store"
            )

        head = _git(["rev-parse", "HEAD"], "bead.publication_conflict_replay.head")
        if head.returncode != 0 or not head.stdout.strip():
            _refuse("could not read the beads clone HEAD")
        head_sha = head.stdout.strip()

        symbolic = _git(
            ["symbolic-ref", "--quiet", "HEAD"],
            "bead.publication_conflict_replay.branch",
        )
        if symbolic.returncode != 0:
            _refuse("the beads clone is on a detached HEAD; refusing to reset")
        branch = symbolic.stdout.strip().removeprefix("refs/heads/")

        git_dir_result = _git(
            ["rev-parse", "--absolute-git-dir"],
            "bead.publication_conflict_replay.git_dir",
        )
        git_dir_text = git_dir_result.stdout.strip()
        git_dir = Path(git_dir_text) if git_dir_text else None
        markers = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD")
        if git_dir is not None and any(
            (git_dir / marker).exists() for marker in markers
        ):
            _refuse("a git operation is still in progress in the beads clone")

        if head_sha == launch_base:
            _refuse("the beads store holds no unpublished commits for this attempt")

        rev_list = _git(
            ["rev-list", f"{launch_base}..HEAD"],
            "bead.publication_conflict_replay.range",
        )
        if rev_list.returncode != 0:
            _refuse(
                "could not list the unpublished commits: "
                f"{(rev_list.stderr or rev_list.stdout or '').strip()}"
            )
        unpublished = [line for line in rev_list.stdout.splitlines() if line.strip()]
        if not unpublished:
            _refuse("the beads store holds no unpublished commits for this attempt")
        allowed = {sha for sha in (checkpoint_sha, attempt_tip_sha) if sha is not None}
        if not allowed:
            _refuse("this attempt recorded no checkpoint commit to compare against")
        foreign = [sha for sha in unpublished if sha not in allowed]
        if foreign:
            _refuse(
                "commit "
                + ", ".join(foreign)
                + " is not part of this attempt's unpublished graph"
            )

        status = _git(
            ["status", "--porcelain"],
            "bead.publication_conflict_replay.status",
        )
        if status.returncode != 0:
            _refuse("could not inspect the beads worktree for tracked changes")
        tracked_changes = [
            line for line in status.stdout.splitlines() if not line.startswith("??")
        ]
        if tracked_changes:
            _refuse("the beads worktree has other tracked changes")

        import time

        from sase.sdd._repository_recovery_git import (
            recovery_ref,
            update_and_verify_ref,
            verify_managed_reset,
        )

        ref = recovery_ref(repo_root, epic_id, head_sha, time.time())

        def _locked_runner(
            root: Path, args: list[str], *, op: str, network: bool = False
        ) -> subprocess.CompletedProcess[Any]:
            del network
            return run_sdd_git(
                args,
                cwd=root,
                op=op,
                check=False,
                capture_output=True,
                text=True,
            )

        try:
            preserve_problem = update_and_verify_ref(
                repo_root,
                ref,
                head_sha,
                _locked_runner,
                "bead.publication_conflict_replay",
            )
        except Exception as exc:
            _refuse(f"timed out preserving the unpublished graph: {exc}")
        if preserve_problem is not None:
            _refuse(preserve_problem)

        reset = _git(
            ["reset", "--hard", "@{upstream}"],
            "bead.publication_conflict_replay.reset",
        )
        if reset.returncode != 0:
            _refuse(
                "could not reset the beads clone to upstream: "
                f"{(reset.stderr or reset.stdout or '').strip()}; the "
                f"unpublished graph is preserved under {ref}"
            )
        reset_problem = verify_managed_reset(
            repo_root,
            branch=branch,
            upstream_sha=upstream_sha,
            runner=_locked_runner,
        )
        if reset_problem is not None:
            _refuse(f"{reset_problem}; the unpublished graph is preserved under {ref}")
        return ref


def _publication_replay_refusal_message(
    *,
    cause: str,
    epic_id: str,
    beads_dir: Path,
    archived_path: Path,
    reason: str,
) -> str:
    """Render the no-reset failure: cause first, then manual recovery."""
    return (
        f"{cause}\n"
        f"The unpublished launch graph for {epic_id} was NOT discarded: "
        f"{reason}.\n"
        "Recover manually:\n"
        f"  1. rescue the unpublished commits, e.g. `git -C {beads_dir} "
        "update-ref refs/sase/recovery/<name> HEAD`;\n"
        f"  2. reset the beads clone to upstream: `git -C {beads_dir} fetch "
        f"&& git -C {beads_dir} reset --hard @{{upstream}}`;\n"
        f"  3. remove the plan's `bead_id` header from {archived_path};\n"
        f"  4. rerun `sase bead work {archived_path}`.\n"
        "For broader diagnostics, run `sase doctor -v`."
    )


__all__ = [
    "PlanFileWorkLaunchHooks",
    "checkpoint_and_publish_graph",
    "resume_linked_epic",
    "work_from_plan_file_locked",
]
