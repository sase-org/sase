"""Recovery path for checkpointed commit workflows."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from sase.llm_provider.commit_finalizer_git_status import git_changed_files
from sase.output import print_status
from sase.telemetry.metrics import VCS_OPERATIONS
from sase.workspace_provider.utils import reconcile_managed_checkout_origin
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit.runtime_tags import (
    run_owned_commit_tags,
    update_trailing_commit_tags,
)
from sase.workflows.commit.workflow_support import resolve_head_commit_sha
from sase.workflows.commit.workflow_support import resolve_head_tree_id
from sase.workflows.commit.workflow_types import RunResult

if TYPE_CHECKING:
    from sase.workflows.commit.workflow import CommitWorkflow


def resume_commit_workflow(
    workflow_type: type[CommitWorkflow],
    *,
    bead_action: str | None = None,
    checkpoint_load: Callable[[], CommitCheckpoint | None],
    checkpoint_save: Callable[[CommitCheckpoint], str | None],
    checkpoint_delete: Callable[[], None],
    get_vcs_provider: Callable[[str], object],
    is_conflict_state: Callable[[object, str], bool],
) -> RunResult:
    """Resume a checkpoint after manual conflict resolution."""
    cp = checkpoint_load()
    if cp is None:
        print_status("No commit checkpoint found — nothing to resume", "error")
        return RunResult.FAILED
    if not _normalize_checkpoint_bead_action(cp, bead_action, checkpoint_save):
        return RunResult.FAILED

    wf = workflow_type(payload=cp.payload, method=cp.method)
    wf._base_cl_name = cp.base_cl_name
    wf._reserved_name = cp.reserved_name
    wf._parent_cl_name = cp.parent_cl_name
    wf._diff_path = cp.diff_path
    wf._cl_name = cp.cl_name
    wf._project_file = cp.project_file

    reconcile_managed_checkout_origin(cp.cwd)
    provider = get_vcs_provider(cp.cwd)
    provider_name = getattr(provider, "_provider_name", "unknown")

    if is_conflict_state(provider, cp.cwd):
        print_status(
            "Conflicts are still in progress — complete the rebase/merge "
            "first, then re-run sase stitch create --resume",
            "error",
        )
        VCS_OPERATIONS.labels(
            provider=provider_name,
            operation="commit_resume",
            status="conflict",
        ).inc()
        return RunResult.CONFLICT

    expected_subject = (cp.payload.get("message", "").splitlines() or [""])[0].strip()
    actual_subject = _get_head_subject(provider, cp.cwd)
    subject_mismatch = bool(
        expected_subject
        and (actual_subject is None or actual_subject.strip() != expected_subject)
    )
    if cp.no_commit_dispatched or subject_mismatch:
        dirty_paths = git_changed_files(cp.cwd)
        if cp.no_commit_dispatched or not dirty_paths:
            return _finish_no_commit_resume(
                cp,
                checkpoint_delete,
                provider_name,
                dirty_paths=dirty_paths,
            )

    if subject_mismatch:
        print_status(
            "Could not find the expected commit at HEAD (subject mismatch). "
            "Re-run sase stitch create from scratch.",
            "error",
        )
        VCS_OPERATIONS.labels(
            provider=provider_name,
            operation="commit_resume",
            status="failed",
        ).inc()
        return RunResult.FAILED

    if (
        cp.method in ("create_commit", "create_pull_request")
        and "dispatch" not in cp.completed_steps
    ):
        restamp_failure = _restamp_missing_footer_tags(provider, cp, provider_name)
        if restamp_failure is not None:
            return restamp_failure
        try:
            ok, err = provider.finalize_commit(  # type: ignore[attr-defined]
                cp.payload, cp.cwd
            )
        except NotImplementedError:
            print_status(
                "finalize_commit not supported by this VCS provider; "
                "skipping push/amend and replaying tracking only.",
                "warning",
            )
        else:
            if not ok:
                recorded = wf._record_unpushed_commit_marker_if_present(
                    cp, provider, err
                )
                if recorded is not None:
                    print_status(
                        f"finalize_commit created local commit {cp.commit_sha} "
                        f"but failed before publishing it: {err}."
                        f"{_unpushed_persistence_detail(recorded)}",
                        "error",
                    )
                else:
                    print_status(f"finalize_commit failed: {err}", "error")
                VCS_OPERATIONS.labels(
                    provider=provider_name,
                    operation="commit_resume",
                    status="failed",
                ).inc()
                return RunResult.FAILED
        # The original dispatch never recorded a SHA when it ended in
        # CONFLICT (cp.dispatch_result stayed None), so this is the only
        # point that has the repo and the finalized HEAD in hand. Resolve
        # here, after any restamp/bead amend and the finalize push (which may
        # itself have rebased), so the run-owned ledger carries the commit
        # this resume actually finalized instead of a null result.
        cp.commit_sha = resolve_head_commit_sha(provider, cp.cwd)
        cp.commit_tree = resolve_head_tree_id(provider, cp.cwd)
        if cp.dispatch_result is None:
            cp.dispatch_result = cp.commit_sha
        cp.pushed = True
        cp.dispatch_error = None
        cp.completed_steps.append("dispatch")
        checkpoint_save(cp)

    wf._run_file_hooks(cp, provider)

    if not wf._run_after_hook(cp):
        VCS_OPERATIONS.labels(
            provider=provider_name,
            operation="commit_resume",
            status="failed",
        ).inc()
        return RunResult.FAILED

    _reconcile_patch_from_project_file(wf, cp, checkpoint_save)

    tracking_result = wf._run_tracking_steps(cp, cp.dispatch_result)
    if tracking_result != RunResult.OK:
        VCS_OPERATIONS.labels(
            provider=provider_name,
            operation="commit_resume",
            status="failed",
        ).inc()
        return tracking_result

    checkpoint_delete()
    VCS_OPERATIONS.labels(
        provider=provider_name,
        operation="commit_resume",
        status="ok",
    ).inc()
    return RunResult.OK


def _normalize_checkpoint_bead_action(
    cp: CommitCheckpoint,
    bead_action: str | None,
    checkpoint_save: Callable[[CommitCheckpoint], str | None],
) -> bool:
    payload = cp.payload if isinstance(cp.payload, dict) else {}
    bead_id = str(payload.get("bead_id") or "").strip()
    saved = payload.get("bead_action")
    if saved is not None and saved not in {"close", "keep"}:
        print_status(
            "Commit checkpoint contains an invalid bead_action. Re-run "
            "`sase stitch create --resume -B close` or `-B keep` after "
            "repairing the checkpoint.",
            "error",
        )
        return False
    if bead_action is not None and bead_action not in {"close", "keep"}:
        print_status("bead_action must be either close or keep", "error")
        return False
    if saved is not None:
        if bead_action is not None and bead_action != saved:
            print_status(
                "Commit checkpoint already saved bead_action "
                f"{saved!r}; refusing conflicting resume action {bead_action!r}.",
                "error",
            )
            return False
        payload.pop("do_not_close_bead", None)
        return True
    if not bead_id:
        if bead_action == "close":
            print_status("there is no assigned bead to close", "error")
            return False
        if bead_action == "keep":
            payload["bead_action"] = "keep"
            checkpoint_save(cp)
        payload.pop("do_not_close_bead", None)
        return True
    if bead_action is None:
        print_status(
            "This legacy commit checkpoint is associated with bead "
            f"{bead_id} but has no saved bead_action. Re-run "
            "`sase stitch create --resume -B keep` for intermediate work or "
            "`sase stitch create --resume -B close` after the bead is complete.",
            "error",
        )
        return False
    payload["bead_action"] = bead_action
    payload.pop("do_not_close_bead", None)
    checkpoint_save(cp)
    return True


def _finish_no_commit_resume(
    cp: CommitCheckpoint,
    checkpoint_delete: Callable[[], None],
    provider_name: str,
    *,
    dirty_paths: list[str],
) -> RunResult:
    """Complete a checkpoint whose original dispatch never produced a commit."""
    if dirty_paths:
        print_status(
            "The original stitch never created a commit, and the repository "
            "still has stageable changes: "
            + ", ".join(dirty_paths)
            + ". Re-run `sase stitch create` from scratch.",
            "error",
        )
        checkpoint_delete()
        VCS_OPERATIONS.labels(
            provider=provider_name,
            operation="commit_resume",
            status="never_committed_dirty",
        ).inc()
        return RunResult.FAILED

    print_status(
        "Checkpointed stitch has nothing to finish: no commit was created, "
        "or its changes were already upstream.",
        "success",
    )
    checkpoint_delete()
    VCS_OPERATIONS.labels(
        provider=provider_name,
        operation="commit_resume",
        status="no_commit_needed",
    ).inc()
    return RunResult.OK


def _restamp_missing_footer_tags(
    provider: object, cp: CommitCheckpoint, provider_name: str
) -> RunResult | None:
    """Re-stamp HEAD's SASE_* footer tags dropped during conflict resolution.

    Reaching here means HEAD's subject already matched the checkpointed
    payload, which conflict resolution can pass even after rewriting the
    message body and dropping its provenance tags — the dispatch response
    that would otherwise carry them was also lost to ``CONFLICT``. Re-stamp
    here, before ``finalize_commit`` pushes, so the run's own commit stays
    attributable without touching the author's rewritten body. Returns a
    terminal :class:`RunResult` when the resume must abort with HEAD left
    unpushed and recoverable, or ``None`` to continue.
    """
    expected = run_owned_commit_tags(str(cp.payload.get("message") or ""))
    if not expected:
        return None

    try:
        ok, head_message = provider.get_description(  # type: ignore[attr-defined]
            "HEAD", cp.cwd
        )
    except NotImplementedError:
        return None
    if not ok or head_message is None:
        print_status(
            "Could not read HEAD's commit message to verify SASE provenance "
            "tags before resuming. HEAD is left unpushed and recoverable — "
            "resolve manually and re-run sase stitch create --resume.",
            "error",
        )
        VCS_OPERATIONS.labels(
            provider=provider_name,
            operation="commit_resume",
            status="failed",
        ).inc()
        return RunResult.FAILED

    current = run_owned_commit_tags(head_message)
    missing = {
        key: value for key, value in expected.items() if current.get(key) != value
    }
    if not missing:
        return None

    new_message = update_trailing_commit_tags(head_message, missing)
    try:
        amend_ok, amend_err = provider.amend(  # type: ignore[attr-defined]
            new_message, cp.cwd, no_upload=True
        )
    except NotImplementedError:
        amend_ok, amend_err = False, "amend is not supported by this VCS provider"
    if not amend_ok:
        print_status(
            "Could not re-stamp SASE provenance tags onto HEAD before "
            f"resuming: {amend_err}. HEAD is left unpushed and recoverable — "
            "resolve manually and re-run sase stitch create --resume.",
            "error",
        )
        VCS_OPERATIONS.labels(
            provider=provider_name,
            operation="commit_resume",
            status="failed",
        ).inc()
        return RunResult.FAILED

    print_status(
        "Re-stamped SASE provenance tags onto HEAD after conflict "
        "resolution dropped them.",
        "info",
    )
    return None


def _get_head_subject(provider: object, cwd: str) -> str | None:
    """Return the subject line of the HEAD commit, or None if unavailable."""
    try:
        ok, desc = provider.get_description(  # type: ignore[attr-defined]
            "HEAD", cwd, short=True
        )
    except NotImplementedError:
        return None
    except Exception:
        return None
    if not ok or not desc:
        return None
    return desc.strip().splitlines()[0] if desc.strip() else ""


def _reconcile_patch_from_project_file(
    wf: CommitWorkflow,
    cp: CommitCheckpoint,
    checkpoint_save: Callable[[CommitCheckpoint], str | None],
) -> None:
    """Checkpoint a Patch already recorded by a prior attempt."""
    if wf._method != "create_pull_request":
        return
    if "create_patch" in cp.completed_steps:
        return
    candidate = cp.cs_name or wf._reserved_name
    if not candidate or not wf._project_file:
        return
    if _changespec_name_in_project_file(wf._project_file, candidate):
        cp.cs_name = candidate
        cp.completed_steps.append("create_patch")
        checkpoint_save(cp)


def _changespec_name_in_project_file(project_file: str, cl_name: str) -> bool:
    if not os.path.isfile(project_file):
        return False
    try:
        with open(project_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("NAME: ") and line[6:].strip() == cl_name:
                    return True
    except OSError:
        return False
    return False


def _unpushed_persistence_detail(recorded: object) -> str:
    durable = bool(getattr(recorded, "durable", False))
    failures = [str(item) for item in getattr(recorded, "failure_details", [])]
    if durable:
        if not failures:
            return " Run `sase stitch create --resume` to retry the push."
        return (
            " Recovery evidence was partially recorded; "
            + "; ".join(failures)
            + ". Run `sase stitch create --resume` to retry from the durable "
            "checkpoint or marker."
        )
    detail = "; ".join(failures) or "unknown persistence failure"
    return (
        " Automatic recovery evidence could not be recorded: "
        + detail
        + ". The local commit remains in the repository; inspect it manually "
        "before retrying."
    )
