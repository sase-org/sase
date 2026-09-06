"""CommitWorkflow class for dispatching VCS commit operations."""

from __future__ import annotations

import logging
import os

from sase.output import print_status
from sase.ace.deltas import refresh_deltas_after_commits_change
from sase.telemetry.metrics import VCS_OPERATIONS
from sase.vcs_provider import get_vcs_provider
from sase.workflows.base import BaseWorkflow
from sase.workflows.commit.checkpoint import (
    CommitCheckpoint,
    checkpoint_delete,
    checkpoint_load,
    checkpoint_save,
)
from sase.workflows.commit.commit_tracking import (
    append_commits_entry,
    capture_pre_commit_diff,
    cleanup_reservation,
    create_patch,
    resolve_cl_name,
    resolve_project_file,
    write_result_marker,
)
from sase.workflows.commit.bead_hooks import (
    apply_bead_commit_tag,
    close_assigned_bead_after_commit,
    handle_beads,
)
from sase.workflows.commit.command_hooks import (
    run_after_commit_hook,
    run_before_commit_hook,
)
from sase.workflows.commit.message_validation import (
    check_commit_message,
    load_commit_message_policy,
)
from sase.workflows.commit.plan_hooks import handle_sase_plan
from sase.workflows.commit.pr_operations import (
    append_pr_tags,
    apply_project_pr_prefix,
    build_pr_body,
    detect_parent_patch,
)
from sase.workflows.commit.runtime_tags import apply_runtime_commit_tags
from sase.workflows.commit.runtime_tags import apply_tracked_commit_tags
from sase.workflows.commit.runtime_tags import resolve_local_agent_name
from sase.workflows.commit.workflow_publication import run_agent_publication_step
from sase.workflows.commit.workflow_resume import resume_commit_workflow
from sase.workflows.commit.workflow_support import (
    classify_dispatch_failure as _classify_dispatch_failure,
)
from sase.workflows.commit.workflow_support import (
    explicit_parent_resolves as _explicit_parent_resolves,
)
from sase.workflows.commit.workflow_support import (
    is_conflict_state as _is_conflict_state,
)
from sase.workflows.commit.workflow_support import (
    log_commit_failed as _log_commit_failed,
)
from sase.workflows.commit.workflow_support import resolve_head_commit_sha
from sase.workflows.commit.workflow_support import resolve_head_tree_id
from sase.workflows.commit.workflow_types import (
    EXIT_CODE_CONFLICT,
    METHOD_ALIASES,
    VALID_METHODS,
    RunResult,
)

_logger = logging.getLogger(__name__)


class CommitWorkflow(BaseWorkflow):
    """A workflow that dispatches commit operations to VCS provider hooks."""

    def __init__(self, payload: dict, method: str) -> None:
        self._payload = payload
        self._method = method
        self._base_cl_name: str | None = None
        self._reserved_name: str | None = None
        self._parent_cl_name: str | None = None
        self._diff_path: str | None = None
        self._cl_name: str | None = None
        self._project_file: str | None = None

    @property
    def name(self) -> str:
        return "commit"

    @property
    def description(self) -> str:
        return "Dispatch a VCS commit operation via JSON payload"

    def run(self) -> RunResult:
        if self._method not in VALID_METHODS:
            aliases = ", ".join(f"{a} -> {c}" for a, c in METHOD_ALIASES.items())
            print_status(
                f"Unknown commit method '{self._method}'. "
                f"Valid methods: {', '.join(VALID_METHODS)} "
                f"(aliases: {aliases})",
                "error",
            )
            _log_commit_failed(self._method, "other")
            return RunResult.FAILED

        if not isinstance(self._payload, dict):
            print_status("Payload must be a JSON object.", "error")
            _log_commit_failed(self._method, "other")
            return RunResult.FAILED
        if "message" not in self._payload and self._method != "create_pull_request":
            print_status("Payload missing required 'message' field.", "error")
            _log_commit_failed(self._method, "other")
            return RunResult.FAILED
        if self._method == "create_pull_request" and not self._payload.get("name"):
            print_status(
                "Payload missing required 'name' field for create_pull_request.",
                "error",
            )
            _log_commit_failed(self._method, "other")
            return RunResult.FAILED

        policy = load_commit_message_policy()
        rejection = check_commit_message(
            str(self._payload.get("message") or ""), policy
        )
        if rejection is not None:
            print_status(rejection, "error")
            _log_commit_failed(self._method, "invalid_message")
            return RunResult.FAILED

        cwd = os.getcwd()
        provider = None
        provider_lookup_error: Exception | None = None
        try:
            provider = get_vcs_provider(cwd)
        except Exception as exc:
            provider_lookup_error = exc
        else:
            if _is_conflict_state(provider, cwd):
                checkpoint_save(
                    CommitCheckpoint(
                        method=self._method,
                        payload=self._payload,
                        cwd=cwd,
                        no_commit_dispatched=True,
                    )
                )
                _log_commit_failed(self._method, "sync_conflict")
                VCS_OPERATIONS.labels(
                    provider=getattr(provider, "_provider_name", "unknown"),
                    operation="commit_conflict_detected",
                    status="pre_existing",
                ).inc()
                print_status(
                    f"{self._method} cannot start: the repository already has "
                    "an in-progress rebase/merge left by a previous "
                    "operation. No commit was created. Resolve or abort the "
                    "in-progress operation, then run "
                    "`sase stitch create --resume`.",
                    "warning",
                )
                return RunResult.CONFLICT

        if self._payload.get("exclude"):
            if provider is None:
                assert provider_lookup_error is not None
                raise provider_lookup_error
            if not provider.supports_commit_excludes():
                from sase.vcs_provider._registry import detect_vcs

                provider_name = detect_vcs(cwd) or "unknown"
                print_status(
                    f"The '{provider_name}' VCS provider does not support "
                    "-x/--exclude on commit dispatch.",
                    "error",
                )
                _log_commit_failed(self._method, "other")
                return RunResult.FAILED

        apply_bead_commit_tag(self._payload, cwd=cwd)

        # Bead lifecycle and SASE_PLAN: skip for proposals.
        # Must run before the before-hook so plan files are in place for formatting.
        if self._method != "create_proposal":
            handle_beads(self._payload, cwd, method=self._method)
            handle_sase_plan(self._payload, cwd)

        # Run commit_hooks.before (e.g. `just fix`) after all files are staged.
        if not run_before_commit_hook(cwd):
            _log_commit_failed(self._method, "before_hook_failed")
            return RunResult.FAILED

        # Pre-compute the _<N> suffix for create_pull_request so the PR branch is
        # created with the correct suffixed name (important for non-git VCS
        # where Patch creation may not be able to rename the branch later).
        # Save the base name so _create_patch can pass it (un-suffixed)
        # to add_patch_to_project_file, which adds its own suffix.
        self._base_cl_name = None
        if self._method == "create_pull_request":
            base_name: str = self._payload["name"]
            self._base_cl_name = base_name
            try:
                from sase.workflows.commit.patch_operations import (
                    compute_suffixed_cl_name,
                )
                from sase.workflows.utils import get_project_from_workspace

                project_name = get_project_from_workspace()
                if project_name:
                    suffixed = compute_suffixed_cl_name(
                        project_name, base_name, cwd=cwd
                    )
                    if suffixed:
                        self._payload["name"] = suffixed
                        self._reserved_name = suffixed
            except Exception:
                pass  # Best-effort; fall back to unsuffixed name

        # Resolve parent Patch: explicit flag takes precedence, then auto-detect
        if self._method == "create_pull_request":
            explicit_parent = self._payload.get("parent")
            if explicit_parent:
                self._parent_cl_name = str(explicit_parent)
                if not _explicit_parent_resolves(self._parent_cl_name):
                    print_status(
                        f"Explicit parent '{self._parent_cl_name}' does not "
                        "resolve to an existing Patch — dropping it so "
                        "it does not leak into the PARENT field.",
                        "warning",
                    )
                    self._parent_cl_name = None
                    self._payload.pop("parent", None)
            else:
                self._parent_cl_name = detect_parent_patch(
                    self._base_cl_name, self._payload
                )

        if self._method == "create_pull_request":
            apply_project_pr_prefix(self._payload)
            append_pr_tags(self._payload, self._parent_cl_name)
            apply_runtime_commit_tags(self._payload)
            build_pr_body(self._payload)
        elif self._method == "create_commit":
            apply_tracked_commit_tags(self._payload)

        if provider is None:
            assert provider_lookup_error is not None
            raise provider_lookup_error
        dispatch = getattr(provider, self._method)

        # Resolve Patch name and project file for COMMITS entries and diff
        # capture.  Cached on self so both capture and append use the same
        # values without double resolution.
        self._cl_name = resolve_cl_name()
        self._project_file = resolve_project_file()

        # Capture diff before VCS commit so it can be recorded in the
        # COMMITS entry.  After the commit the working-tree diff is empty.
        self._diff_path = capture_pre_commit_diff(provider, cwd, self._cl_name)

        # Snapshot the post-mutation payload + resolved fields so the resume
        # path can replay tracking even if dispatch crashes.
        cp = CommitCheckpoint(
            method=self._method,
            payload=self._payload,
            cwd=cwd,
            cl_name=self._cl_name,
            project_file=self._project_file,
            diff_path=self._diff_path,
            base_cl_name=self._base_cl_name,
            reserved_name=self._reserved_name,
            parent_cl_name=self._parent_cl_name,
            publication_agent=resolve_local_agent_name(),
        )
        checkpoint_save(cp)

        print_status(f"Dispatching {self._method} to VCS provider...", "progress")
        ok, result = dispatch(self._payload, cwd)
        if not ok:
            if _is_conflict_state(provider, cwd):
                if _classify_dispatch_failure(result) == "no_staged_changes":
                    cp.no_commit_dispatched = True
                    checkpoint_save(cp)
                _log_commit_failed(self._method, "sync_conflict")
                VCS_OPERATIONS.labels(
                    provider=getattr(provider, "_provider_name", "unknown"),
                    operation="commit_conflict_detected",
                    status="ok",
                ).inc()
                print_status(
                    f"{self._method} hit a merge conflict: {result}. "
                    "Resolve the conflict, then run "
                    "`sase stitch create --resume` to finish.",
                    "warning",
                )
                return RunResult.CONFLICT
            print_status(f"{self._method} failed: {result}", "error")
            _log_commit_failed(self._method, _classify_dispatch_failure(result))
            cleanup_reservation(self._reserved_name)
            checkpoint_delete()
            return RunResult.FAILED

        # If dispatch had to re-suffix the branch to dodge a remote-branch
        # collision, re-point the Patch reservation at the branch that was
        # actually pushed so the recorded NAME matches the PR branch.
        if self._method == "create_pull_request" and self._payload.get("_resuffixed"):
            self._repoint_reservation_after_resuffix()
            cp.reserved_name = self._reserved_name

        if self._method in ("create_commit", "create_pull_request"):
            cp.commit_sha = resolve_head_commit_sha(provider, cwd)
            cp.commit_tree = resolve_head_tree_id(provider, cwd)
        cp.dispatch_result = result
        cp.completed_steps.append("dispatch")
        checkpoint_save(cp)

        self._run_file_hooks(cp, provider)

        if not self._run_after_hook(cp):
            return RunResult.FAILED

        print_status(f"{self._method} completed successfully!", "success")

        tracking_result = self._run_tracking_steps(cp, result)
        if tracking_result != RunResult.OK:
            return tracking_result

        checkpoint_delete()
        return RunResult.OK

    def _run_file_hooks(self, cp: CommitCheckpoint, provider: object) -> None:
        """Capture a committed revision once without gating the workflow."""
        if self._method not in ("create_commit", "create_pull_request"):
            return
        if "file_hooks" in cp.completed_steps:
            return
        from sase.config.file_hooks import load_file_hooks
        from sase.file_hooks.producer import produce_commit_file_hooks

        try:
            hooks = load_file_hooks()
        except Exception:
            produce_commit_file_hooks(
                repo_root=cp.cwd,
                commit_sha=cp.commit_sha,
                provider=provider,  # type: ignore[arg-type]
                project_file=cp.project_file,
                producer="commit",
            )
            cp.completed_steps.append("file_hooks")
            checkpoint_save(cp)
            return
        commit_sha = cp.commit_sha
        if hooks and not commit_sha:
            try:
                commit_sha = provider.revision_id(  # type: ignore[attr-defined]
                    "HEAD", cp.cwd
                )
            except Exception:
                _logger.warning(
                    "File-hook commit SHA lookup failed; continuing",
                    exc_info=True,
                )
        produce_commit_file_hooks(
            repo_root=cp.cwd,
            commit_sha=commit_sha,
            provider=provider,  # type: ignore[arg-type]
            project_file=cp.project_file,
            producer="commit",
            hooks=hooks,
        )
        cp.completed_steps.append("file_hooks")
        checkpoint_save(cp)

    def _run_after_hook(self, cp: CommitCheckpoint) -> bool:
        """Run and checkpoint the post-dispatch hook when this method commits."""
        if self._method not in ("create_commit", "create_pull_request"):
            return True
        if "after_hook" in cp.completed_steps:
            return True
        if not run_after_commit_hook(cp.cwd):
            _log_commit_failed(self._method, "after_hook_failed")
            print_status(
                "The commit may already be pushed. Fix the after-hook failure, "
                "then run `sase stitch create --resume`; do not create a "
                "replacement commit in this repository.",
                "error",
            )
            return False
        cp.completed_steps.append("after_hook")
        checkpoint_save(cp)
        return True

    def _repoint_reservation_after_resuffix(self) -> None:
        """Move the Patch reservation to a re-suffixed PR branch name.

        When the VCS dispatch renames the branch to escape a remote collision
        it records the new name in ``payload["name"]``.  Drop the now-stale
        reservation stub and adopt the new name as ``_reserved_name`` so the
        Patch is created under the branch that was actually pushed.
        """
        new_name = self._payload.get("name")
        if not new_name or new_name == self._reserved_name:
            return
        try:
            from sase.workflows.commit.patch_operations import remove_reservation
            from sase.workflows.utils import get_project_from_workspace

            project_name = get_project_from_workspace()
            if project_name and self._reserved_name:
                remove_reservation(project_name, self._reserved_name)
        except Exception:
            pass  # Best-effort cleanup; the Patch still uses the new name.
        self._reserved_name = new_name

    def _run_tracking_steps(
        self, cp: CommitCheckpoint, result: str | None
    ) -> RunResult:
        """Run the post-dispatch tracking steps and update *cp* as each completes.

        Steps already listed in ``cp.completed_steps`` are skipped so this
        helper is reusable from the resume path.  Returns ``RunResult.OK``
        when every applicable step succeeds.
        """
        if self._method == "create_pull_request":
            if "create_patch" in cp.completed_steps:
                cs_name = cp.cs_name
            else:
                cs_name = create_patch(
                    self._payload,
                    self._base_cl_name,
                    self._parent_cl_name,
                    self._reserved_name,
                    pr_url=result,
                )
                if cs_name is None:
                    cleanup_reservation(self._reserved_name)
                else:
                    cp.cs_name = cs_name
                    cp.completed_steps.append("create_patch")
                    checkpoint_save(cp)
        else:
            cs_name = cp.cs_name

        if "write_result_marker" not in cp.completed_steps:
            write_result_marker(
                self._method,
                self._payload,
                self._diff_path,
                result,
                cs_name,
                commit_sha=cp.commit_sha,
                commit_tree=cp.commit_tree,
                commit_cwd=cp.cwd,
            )
            cp.completed_steps.append("write_result_marker")
            checkpoint_save(cp)

        publication_result = self._run_agent_publication_step(cp)
        if publication_result != RunResult.OK:
            return publication_result

        if self._method in ("create_commit", "create_proposal"):
            if "append_commits_entry" in cp.completed_steps:
                entry_id = cp.entry_id
            else:
                entry_id = append_commits_entry(
                    self._project_file,
                    self._cl_name,
                    self._payload,
                    self._method,
                    self._diff_path,
                    expected_entry_id=cp.entry_id,
                )
                if entry_id:
                    cp.entry_id = entry_id
                    cp.completed_steps.append("append_commits_entry")
                    checkpoint_save(cp)

            if entry_id and "final_result_marker" not in cp.completed_steps:
                write_result_marker(
                    self._method,
                    self._payload,
                    self._diff_path,
                    result,
                    cs_name,
                    entry_id=entry_id,
                    commit_sha=cp.commit_sha,
                    commit_tree=cp.commit_tree,
                    commit_cwd=cp.cwd,
                )
                cp.completed_steps.append("final_result_marker")
                checkpoint_save(cp)

            project_file = self._project_file or cp.project_file
            cl_name = self._cl_name or cp.cl_name
            if project_file and cl_name:
                refresh_deltas_after_commits_change(project_file, cl_name, cp.cwd)

        if (
            self._method in ("create_commit", "create_pull_request")
            and "close_bead" not in cp.completed_steps
            and close_assigned_bead_after_commit(
                cp.payload,
                cp.cwd,
                method=self._method,
            )
        ):
            cp.completed_steps.append("close_bead")
            checkpoint_save(cp)

        return RunResult.OK

    def _run_agent_publication_step(self, cp: CommitCheckpoint) -> RunResult:
        """Publish sidecars after the first durable result marker exists."""
        published = run_agent_publication_step(
            cp,
            self._method,
            checkpoint_save=checkpoint_save,
            get_vcs_provider=get_vcs_provider,
        )
        return RunResult.OK if published else RunResult.FAILED

    @classmethod
    def resume(cls) -> RunResult:
        """Resume a checkpointed commit workflow after manual conflict resolution."""
        return resume_commit_workflow(
            cls,
            checkpoint_load=checkpoint_load,
            checkpoint_save=checkpoint_save,
            checkpoint_delete=checkpoint_delete,
            get_vcs_provider=get_vcs_provider,
            is_conflict_state=_is_conflict_state,
        )
