"""CommitWorkflow class for dispatching VCS commit operations."""

from __future__ import annotations

import os

from sase.output import print_status
from sase.telemetry.metrics import VCS_OPERATIONS
from sase.vcs_provider import get_vcs_provider
from sase.workflows.base import BaseWorkflow
from sase.workspace_provider.utils import reconcile_managed_checkout_origin
from sase.workflows.commit.checkpoint import (
    CommitCheckpoint,
    checkpoint_delete,
    checkpoint_load,
    bind_checkpoint_persistence,
    ensure_operation_id,
)
from sase.workflows.commit.commit_tracking import (
    capture_pre_commit_diff,
    cleanup_reservation,
    resolve_cl_name,
    resolve_project_file,
)
from sase.workflows.commit.bead_hooks import (
    apply_bead_commit_tag,
    handle_beads,
    validate_bead_action_before_commit,
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
from sase.workflows.commit.workflow_resume import resume_commit_workflow
from sase.workflows.commit.workflow_support import (
    classify_dispatch_failure,
    explicit_parent_resolves,
    is_conflict_state,
    log_commit_failed,
)
from sase.workflows.commit.workflow_support import resolve_head_commit_sha
from sase.workflows.commit.workflow_support import resolve_head_tree_id
from sase.workflows.commit._workflow_tracking import (
    CommitWorkflowTrackingMixin,
    emit_stitch_step,
    save_checkpoint,
)
from sase.workflows.commit.workflow_types import (
    EXIT_CODE_CONFLICT,
    METHOD_ALIASES,
    VALID_METHODS,
    RunResult,
)


class CommitWorkflow(CommitWorkflowTrackingMixin, BaseWorkflow):
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
            log_commit_failed(self._method, "other")
            return RunResult.FAILED

        if not isinstance(self._payload, dict):
            print_status("Payload must be a JSON object.", "error")
            log_commit_failed(self._method, "other")
            return RunResult.FAILED
        if "message" not in self._payload and self._method != "create_pull_request":
            print_status("Payload missing required 'message' field.", "error")
            log_commit_failed(self._method, "other")
            return RunResult.FAILED
        if self._method == "create_pull_request" and not self._payload.get("name"):
            print_status(
                "Payload missing required 'name' field for create_pull_request.",
                "error",
            )
            log_commit_failed(self._method, "other")
            return RunResult.FAILED

        policy = load_commit_message_policy()
        rejection = check_commit_message(
            str(self._payload.get("message") or ""), policy
        )
        if rejection is not None:
            print_status(rejection, "error")
            log_commit_failed(self._method, "invalid_message")
            return RunResult.FAILED

        cwd = os.getcwd()
        if not validate_bead_action_before_commit(
            self._payload,
            cwd,
            method=self._method,
        ):
            log_commit_failed(self._method, "other")
            return RunResult.FAILED

        provider = None
        provider_lookup_error: Exception | None = None
        try:
            reconcile_managed_checkout_origin(cwd)
            provider = get_vcs_provider(cwd)
        except Exception as exc:
            provider_lookup_error = exc
        else:
            if is_conflict_state(provider, cwd):
                cp = CommitCheckpoint(
                    method=self._method,
                    payload=self._payload,
                    cwd=cwd,
                    no_commit_dispatched=True,
                    publication_agent=resolve_local_agent_name(),
                    run_id=os.environ.get("SASE_AGENT_TIMESTAMP", "").strip() or None,
                )
                ensure_operation_id(cp)
                save_checkpoint(cp)
                log_commit_failed(self._method, "sync_conflict")
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
                log_commit_failed(self._method, "other")
                return RunResult.FAILED

        apply_bead_commit_tag(self._payload, cwd=cwd)

        # Bead lifecycle and SASE_PLAN: skip for proposals.
        # Must run before the before-hook so plan files are in place for formatting.
        if self._method != "create_proposal":
            handle_beads(self._payload, cwd, method=self._method)
            handle_sase_plan(self._payload, cwd)

        # Run commit_hooks.before (e.g. `just fix`) after all files are staged.
        if not run_before_commit_hook(cwd):
            log_commit_failed(self._method, "before_hook_failed")
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
                if not explicit_parent_resolves(self._parent_cl_name):
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
        # path can replay tracking even if dispatch crashes. The pre-dispatch
        # HEAD is stored separately so publication can name the post-commit SHA.
        pre_dispatch_revision = None
        if self._method in ("create_commit", "create_pull_request"):
            pre_dispatch_revision = resolve_head_commit_sha(provider, cwd)
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
            pre_dispatch_revision=pre_dispatch_revision,
            publication_agent=resolve_local_agent_name(),
            run_id=os.environ.get("SASE_AGENT_TIMESTAMP", "").strip() or None,
        )
        ensure_operation_id(cp)
        save_checkpoint(cp)

        print_status(f"Dispatching {self._method} to VCS provider...", "progress")
        emit_stitch_step(self._method, state="start")
        with bind_checkpoint_persistence(cp):
            ok, result = dispatch(self._payload, cwd)
        if not ok:
            from sase.finalizers.commit_repair_common import bound_stream
            from sase.workflows.commit.rebase_gate_coordinator import is_gate_blocked

            emit_stitch_step(self._method, state="fail", detail=bound_stream(result))
            if is_gate_blocked(self._payload):
                # Explicit rebase gate finding (not a hook-output substring
                # match): keep HEAD local with pushed=false, keep the
                # checkpoint, and return the recoverable conflict result.
                cp.commit_sha = resolve_head_commit_sha(provider, cp.cwd)
                cp.commit_tree = resolve_head_tree_id(provider, cp.cwd)
                cp.pushed = False
                cp.dispatch_error = result
                ensure_operation_id(cp)
                save_checkpoint(cp)
                self._record_unpushed_commit_marker_if_present(cp, provider, result)
                log_commit_failed(self._method, "rebase_gate_findings")
                VCS_OPERATIONS.labels(
                    provider=getattr(provider, "_provider_name", "unknown"),
                    operation="commit_rebase_gate_blocked",
                    status="ok",
                ).inc()
                print_status(
                    f"{self._method} blocked by the rebase gate: {result}",
                    "warning",
                )
                return RunResult.CONFLICT
            if classify_dispatch_failure(result) == "push_failed":
                emit_stitch_step("push", state="fail", detail=bound_stream(result))
            if is_conflict_state(provider, cwd):
                if classify_dispatch_failure(result) == "no_staged_changes":
                    cp.no_commit_dispatched = True
                # Persist stashed gate context so manual resolution and resume
                # cannot bypass the pending check.
                save_checkpoint(cp)
                log_commit_failed(self._method, "sync_conflict")
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
            failure_reason = classify_dispatch_failure(result)
            unpushed = self._record_unpushed_commit_marker_if_present(
                cp, provider, result
            )
            if unpushed is not None:
                detail = self._unpushed_persistence_detail(unpushed)
                print_status(
                    f"{self._method} created local commit {cp.commit_sha} "
                    f"but failed before publishing it: {result}.{detail}",
                    "error",
                )
                log_commit_failed(self._method, failure_reason)
                return RunResult.FAILED
            print_status(f"{self._method} failed: {result}", "error")
            log_commit_failed(self._method, failure_reason)
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
        save_checkpoint(cp)
        emit_stitch_step(self._method, state="ok")
        if self._method in ("create_commit", "create_pull_request"):
            emit_stitch_step("push", state="ok")

        self._run_file_hooks(cp, provider)

        if not self._run_after_hook(cp):
            return RunResult.FAILED

        tracking_result = self._run_tracking_steps(cp, result)
        if tracking_result != RunResult.OK:
            return tracking_result

        print_status(f"{self._method} completed successfully!", "success")
        checkpoint_delete()
        return RunResult.OK

    def _run_after_hook(self, cp: CommitCheckpoint) -> bool:
        """Run and checkpoint the post-dispatch hook when this method commits."""
        if self._method not in ("create_commit", "create_pull_request"):
            return True
        if "after_hook" in cp.completed_steps:
            return True
        if not run_after_commit_hook(cp.cwd):
            log_commit_failed(self._method, "after_hook_failed")
            print_status(
                "The commit may already be pushed. Fix the after-hook failure, "
                "then run `sase stitch create --resume`; do not create a "
                "replacement commit in this repository.",
                "error",
            )
            return False
        cp.completed_steps.append("after_hook")
        save_checkpoint(cp)
        return True

    @classmethod
    def resume(cls, *, bead_action: str | None = None) -> RunResult:
        """Resume a checkpointed commit workflow after manual conflict resolution."""
        return resume_commit_workflow(
            cls,
            bead_action=bead_action,
            checkpoint_load=checkpoint_load,
            checkpoint_save=save_checkpoint,
            checkpoint_delete=checkpoint_delete,
            get_vcs_provider=get_vcs_provider,
            is_conflict_state=is_conflict_state,
        )
