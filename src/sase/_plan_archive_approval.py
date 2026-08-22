"""Shared approval-time plan archiving for every approval surface.

Two surfaces archive an approved plan into its project's SDD plan store: the
gate-response path in :mod:`sase.plan_approval_actions` and the TUI background
worker in
:mod:`sase.ace.tui.actions.agents._notification_plan_background`.  Both start
from notification action data and have to resolve which project the plan
belongs to before a workspace and SDD store can be materialized.

That resolution is the step that regressed silently.  ``project_dir`` in the
action data is the *agent workspace* directory, not a project directory, and
plan gates write it with a trailing slash, so ``os.path.basename`` returned the
empty string and the workspace-plugin lookup was handed
``~/.sase/projects/.sase``.  Every approval-time archive raised and was
swallowed into a log warning.  Resolution now goes through
:func:`sase._plan_approval_artifacts.resolve_plan_action_project_name`, which
prefers ``agent_project_file`` and understands workspace directories, and
failures are reported to the notification inbox instead of only the log.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from sase.bead._sync_publication import PushOutcome

log = logging.getLogger(__name__)

PLAN_ARCHIVE_SENDER = "plan-archive"
_PLAN_ARCHIVE_LEASE_WORKFLOW = "plan-archive"
# Synchronous archive publication waits briefly for a busy sync worker so
# three back-to-back attempts do not all lose the same lock. The global
# push default stays at 0.0.
_PLAN_ARCHIVE_WORKER_LOCK_WAIT_SECONDS = 2.0


class _ApprovedPlanArchive(str):
    """Host-local archive path plus its workspace-independent ``plan:`` ref.

    The string value is the concrete path used inside the operational
    workspace lease. It is diagnostic data for users and compatibility callers,
    not the durable identity a runner should consume across workspaces.
    """

    plan_archive_ref: str

    def __new__(
        cls,
        saved_plan_path: str | Path,
        plan_archive_ref: str,
    ) -> _ApprovedPlanArchive:
        archive = cast(_ApprovedPlanArchive, str.__new__(cls, str(saved_plan_path)))
        archive.plan_archive_ref = plan_archive_ref
        return archive

    @property
    def saved_plan_path(self) -> str:
        return str(self)


class _PlanArchiveProjectError(Exception):
    """Raised when action data does not identify an archivable project."""


def archive_approved_plan(
    action_data: Mapping[str, str],
    src_plan: Path,
    *,
    tier: Literal["tale", "epic"],
    push_after_commit: bool | Literal["async"] | None = None,
) -> _ApprovedPlanArchive:
    """Archive ``src_plan`` into its project's plan store and return its identity.

    Runs inside a durable operational workspace lease -- never the user-owned
    primary checkout -- and publishes the archive commit using
    reset-and-replay semantics: an unpublished HEAD after commit resets the
    SDD store repository (the sidecar clone for remote-backed storage, or
    the checkout itself when plans live in-tree) to its verified upstream
    tip and re-runs the archive. The returned value remains string-compatible
    with the host-local archive path, and also carries ``plan_archive_ref`` as
    the durable workspace-independent identity.

    Raises:
        _PlanArchiveProjectError: If ``action_data`` names no resolvable project.
    """
    from sase._plan_approval_artifacts import (
        resolve_plan_action_project_name,
        resolve_plan_agent_artifacts_dir,
    )
    from sase.bead._sync_publication import has_push_remote, head_is_published
    from sase.sdd._commit_store import push_sdd_store_after_commit
    from sase.sdd.files import (
        commit_sdd_store_files,
        ensure_bare_git_sdd_initialized,
    )
    from sase.sdd.plan_archive import archive_plan_file
    from sase.sdd.plan_refs import canonicalize_plan_reference_from_roots
    from sase.sdd.store import materialize_sdd_store
    from sase.workspace_provider.lease import operational_workspace_lease
    from sase.workspace_provider.ownership import MutationOrigin
    from sase.workspace_provider.reset_replay import ReplayConflict, ResetReplayError

    project_name = resolve_plan_action_project_name(action_data)
    if not project_name:
        raise _PlanArchiveProjectError(
            "no project could be resolved for the approved plan from action data"
            f" keys {sorted(action_data)}"
        )

    # An explicit "async" or `False` keeps the caller's choice (the TUI
    # background worker deliberately never blocks on a push). Unset defaults
    # to a synchronous, verified publication instead of the global async
    # config default, because only a synchronous push can be verified and
    # replayed within this lease's bounded attempts.
    resolved_push_mode = True if push_after_commit is None else push_after_commit
    lock_wait = (
        _PLAN_ARCHIVE_WORKER_LOCK_WAIT_SECONDS if resolved_push_mode is True else 0.0
    )

    artifacts_dir = resolve_plan_agent_artifacts_dir(action_data)
    with operational_workspace_lease(
        project_name,
        workflow=_PLAN_ARCHIVE_LEASE_WORKFLOW,
        holder=PLAN_ARCHIVE_SENDER,
    ) as lease:
        workspace_dir = str(lease.checkout_dir)
        sdd_store = materialize_sdd_store(workspace_dir, lease.workspace_num)
        if sdd_store.is_in_tree:
            ensure_bare_git_sdd_initialized(workspace_dir, commit=True, push=False)

        archive_repo = None if sdd_store.is_in_tree else sdd_store.repo_root
        if archive_repo is not None and _store_has_unpublished_head(archive_repo):
            lease.reset_to_upstream(repo_root=archive_repo)

        def _archive_and_publish() -> _ApprovedPlanArchive:
            archived = archive_plan_file(
                src_plan,
                sdd_store,
                tier=tier,
                preserve_existing=False,
                expect_prompt_snapshot=(tier == "epic"),
            )
            if not sdd_store.is_in_tree:
                commit_result = commit_sdd_store_files(
                    sdd_store,
                    f"Archive approved plan {src_plan.stem}",
                    paths=[archived.path],
                    push_after_commit=resolved_push_mode,
                    artifacts_dir=artifacts_dir,
                    mutation_origin=MutationOrigin.MACHINE,
                    operation_context=lease.operation_context,
                    worker_lock_wait=lock_wait,
                )
                if resolved_push_mode is True and has_push_remote(sdd_store.repo_root):
                    outcome = commit_result.push
                    if outcome is None and not head_is_published(sdd_store.repo_root):
                        outcome = push_sdd_store_after_commit(
                            sdd_store,
                            push_after_commit=True,
                            worker_lock_wait=lock_wait,
                        )
                    _raise_for_archive_push(outcome, sdd_store.repo_root)
                    if not head_is_published(sdd_store.repo_root):
                        raise ReplayConflict(
                            f"{sdd_store.repo_root} HEAD was not published "
                            "after the archive commit"
                        )
            archive_ref = canonicalize_plan_reference_from_roots(
                archived.path,
                roots=(sdd_store.kind_root("plans"),),
            )
            if archive_ref is None:
                raise ReplayConflict(
                    f"archived plan is outside the resolved plans root: {archived.path}"
                )
            return _ApprovedPlanArchive(archived.path, archive_ref)

        try:
            result = lease.reset_and_replay(
                _archive_and_publish,
                repo_root=archive_repo,
            )
        except ResetReplayError as exc:
            recovery_ref = None
            if archive_repo is not None:
                try:
                    recovery_ref = lease.reset_to_upstream(repo_root=archive_repo)
                except Exception:
                    log.debug(
                        "failed to reset the SDD store after archive exhaustion",
                        exc_info=True,
                    )
            raise ResetReplayError(
                str(exc.last_error) if exc.last_error is not None else str(exc),
                attempts=exc.attempts,
                last_error=exc.last_error,
                recovery_ref=recovery_ref,
            ) from exc
        return result.value


def _store_has_unpublished_head(repo_root: Path) -> bool:
    from sase.bead._sync_publication import has_push_remote, head_is_published

    # Local and not-yet-materialized stores have no clone to inspect.
    # ``git remote`` raises if *cwd* does not exist.
    if not repo_root.is_dir():
        return False
    return has_push_remote(repo_root) and not head_is_published(repo_root)


def _raise_for_archive_push(outcome: PushOutcome | None, repo_root: Path) -> None:
    from sase.workspace_provider.reset_replay import ReplayConflict, ReplayDeferred

    if outcome is None or outcome.pushed or outcome.skipped_no_remote:
        return
    if outcome.skipped_locked:
        raise ReplayDeferred(
            f"{repo_root} publication deferred: sync worker lock is held"
        )
    detail = outcome.error or "push was rejected"
    raise ReplayConflict(f"{repo_root} publication failed: {detail}")


def report_plan_archive_failure(
    src_plan: Path | str,
    action_data: Mapping[str, str],
    error: BaseException,
) -> None:
    """Log and surface an approval-time archive failure.

    Archiving stays best-effort -- an approval must never fail because its plan
    could not be filed -- but the failure is no longer log-only.  A silent
    warning is what let every approval-time archive fail for a week without
    anyone noticing.
    """
    plan_path = str(src_plan)
    log.error("Failed to archive approved plan %s", plan_path, exc_info=error)
    try:
        from sase.notifications import notify_workflow_complete

        notify_workflow_complete(
            PLAN_ARCHIVE_SENDER,
            action_data.get("agent_cl_name"),
            False,
            [
                f"Failed to archive approved plan: {Path(plan_path).name}",
                f"{type(error).__name__}: {error}",
                "The plan of record exists only on this machine until it is"
                " archived by a later launch.",
            ],
            extra_files=[plan_path],
            tags=["plan"],
        )
    except Exception:
        log.debug("Failed to report plan archive failure", exc_info=True)
