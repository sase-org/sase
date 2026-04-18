"""CommitWorkflow class for dispatching VCS commit operations."""

from __future__ import annotations

import os
from enum import IntEnum

from sase.output import print_status
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
    create_changespec,
    resolve_cl_name,
    resolve_project_file,
    write_result_marker,
)
from sase.workflows.commit.precommit_hooks import (
    handle_beads,
    handle_sase_plan,
    run_precommit,
)
from sase.workflows.commit.pr_operations import (
    append_pr_tags,
    apply_project_pr_prefix,
    build_pr_body,
    detect_parent_changespec,
)


class RunResult(IntEnum):
    OK = 0
    FAILED = 1
    CONFLICT = 2


EXIT_CODE_CONFLICT = 2

VALID_METHODS = ("create_commit", "create_proposal", "create_pull_request")

METHOD_ALIASES: dict[str, str] = {
    "commit": "create_commit",
    "propose": "create_proposal",
    "pr": "create_pull_request",
}


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
            return RunResult.FAILED

        if not isinstance(self._payload, dict):
            print_status("Payload must be a JSON object.", "error")
            return RunResult.FAILED
        if "message" not in self._payload and self._method != "create_pull_request":
            print_status("Payload missing required 'message' field.", "error")
            return RunResult.FAILED
        if self._method == "create_pull_request" and not self._payload.get("name"):
            print_status(
                "Payload missing required 'name' field for create_pull_request.",
                "error",
            )
            return RunResult.FAILED

        cwd = os.getcwd()

        # Bead lifecycle and SASE_PLAN: skip for proposals.
        # Must run before precommit so plan files are in place for formatting.
        if self._method != "create_proposal":
            handle_beads(self._payload, cwd)
            handle_sase_plan(self._payload, cwd)

        # Run precommit command (e.g. `just fix`) after all files are staged
        if not run_precommit(cwd):
            return RunResult.FAILED

        # Pre-compute the _<N> suffix for create_pull_request so the CL is
        # created with the correct suffixed name (important for non-git VCS
        # where ChangeSpec creation may not be able to rename the CL later).
        # Save the base name so _create_changespec can pass it (un-suffixed)
        # to add_changespec_to_project_file, which adds its own suffix.
        self._base_cl_name = None
        if self._method == "create_pull_request":
            base_name: str = self._payload["name"]
            self._base_cl_name = base_name
            try:
                from sase.workflows.commit.changespec_operations import (
                    compute_suffixed_cl_name,
                )
                from sase.workflows.utils import get_project_from_workspace

                project_name = get_project_from_workspace()
                if project_name:
                    suffixed = compute_suffixed_cl_name(project_name, base_name)
                    if suffixed:
                        self._payload["name"] = suffixed
                        self._reserved_name = suffixed
            except Exception:
                pass  # Best-effort; fall back to unsuffixed name

        # Resolve parent ChangeSpec: explicit flag takes precedence, then auto-detect
        if self._method == "create_pull_request":
            explicit_parent = self._payload.get("parent")
            if explicit_parent:
                self._parent_cl_name = str(explicit_parent)
            else:
                self._parent_cl_name = detect_parent_changespec(
                    self._base_cl_name, self._payload
                )

        if self._method == "create_pull_request":
            apply_project_pr_prefix(self._payload)
            append_pr_tags(self._payload, self._parent_cl_name)
            build_pr_body(self._payload)

        provider = get_vcs_provider(cwd)
        dispatch = getattr(provider, self._method)

        # Resolve CL name and project file for COMMITS entries and diff
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
        )
        checkpoint_save(cp)

        print_status(f"Dispatching {self._method} to VCS provider...", "progress")
        ok, result = dispatch(self._payload, cwd)
        if not ok:
            if _is_conflict_state(provider, cwd):
                VCS_OPERATIONS.labels(
                    provider=getattr(provider, "_provider_name", "unknown"),
                    operation="commit_conflict_detected",
                    status="ok",
                ).inc()
                print_status(
                    f"{self._method} hit a merge conflict: {result}. "
                    "Resolve the conflict, then run "
                    "`sase commit --resume` to finish.",
                    "warning",
                )
                return RunResult.CONFLICT
            print_status(f"{self._method} failed: {result}", "error")
            cleanup_reservation(self._reserved_name)
            checkpoint_delete()
            return RunResult.FAILED

        cp.dispatch_result = result
        cp.completed_steps.append("dispatch")
        checkpoint_save(cp)

        print_status(f"{self._method} completed successfully!", "success")

        tracking_result = self._run_tracking_steps(cp, result)
        if tracking_result != RunResult.OK:
            return tracking_result

        checkpoint_delete()
        return RunResult.OK

    def _run_tracking_steps(
        self, cp: CommitCheckpoint, result: str | None
    ) -> RunResult:
        """Run the post-dispatch tracking steps and update *cp* as each completes.

        Steps already listed in ``cp.completed_steps`` are skipped so this
        helper is reusable from the resume path.  Returns ``RunResult.OK``
        when every applicable step succeeds.
        """
        if self._method == "create_pull_request":
            if "create_changespec" in cp.completed_steps:
                cs_name = cp.cs_name
            else:
                cs_name = create_changespec(
                    self._payload,
                    self._base_cl_name,
                    self._parent_cl_name,
                    self._reserved_name,
                    cl_url=result,
                )
                if cs_name is None:
                    cleanup_reservation(self._reserved_name)
                else:
                    cp.cs_name = cs_name
                    cp.completed_steps.append("create_changespec")
                    checkpoint_save(cp)
        else:
            cs_name = cp.cs_name

        if "write_result_marker" not in cp.completed_steps:
            write_result_marker(
                self._method, self._payload, self._diff_path, result, cs_name
            )
            cp.completed_steps.append("write_result_marker")
            checkpoint_save(cp)

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
                )
                cp.completed_steps.append("final_result_marker")
                checkpoint_save(cp)

        return RunResult.OK

    @classmethod
    def resume(cls) -> RunResult:
        """Resume a checkpointed commit workflow after manual conflict resolution."""
        cp = checkpoint_load()
        if cp is None:
            print_status("No commit checkpoint found — nothing to resume", "error")
            return RunResult.FAILED

        wf = cls(payload=cp.payload, method=cp.method)
        wf._base_cl_name = cp.base_cl_name
        wf._reserved_name = cp.reserved_name
        wf._parent_cl_name = cp.parent_cl_name
        wf._diff_path = cp.diff_path
        wf._cl_name = cp.cl_name
        wf._project_file = cp.project_file

        provider = get_vcs_provider(cp.cwd)
        provider_name = getattr(provider, "_provider_name", "unknown")

        if _is_conflict_state(provider, cp.cwd):
            print_status(
                "Conflicts are still in progress — complete the rebase/merge "
                "first, then re-run sase commit --resume",
                "error",
            )
            VCS_OPERATIONS.labels(
                provider=provider_name,
                operation="commit_resume",
                status="conflict",
            ).inc()
            return RunResult.CONFLICT

        expected_subject = (cp.payload.get("message", "").splitlines() or [""])[
            0
        ].strip()
        actual_subject = _get_head_subject(provider, cp.cwd)
        if expected_subject and (
            actual_subject is None or actual_subject.strip() != expected_subject
        ):
            print_status(
                "Could not find the expected commit at HEAD (subject mismatch). "
                "Re-run sase commit from scratch.",
                "error",
            )
            VCS_OPERATIONS.labels(
                provider=provider_name,
                operation="commit_resume",
                status="failed",
            ).inc()
            return RunResult.FAILED

        if cp.method in ("create_commit", "create_pull_request"):
            try:
                ok, err = provider.finalize_commit(cp.payload, cp.cwd)
            except NotImplementedError:
                print_status(
                    "finalize_commit not supported by this VCS provider; "
                    "skipping push/amend and replaying tracking only.",
                    "warning",
                )
            else:
                if not ok:
                    print_status(f"finalize_commit failed: {err}", "error")
                    VCS_OPERATIONS.labels(
                        provider=provider_name,
                        operation="commit_resume",
                        status="failed",
                    ).inc()
                    return RunResult.FAILED

        _reconcile_changespec_from_project_file(wf, cp)

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


def _reconcile_changespec_from_project_file(
    wf: CommitWorkflow, cp: CommitCheckpoint
) -> None:
    """Mark `create_changespec` complete if the project file already records it.

    Handles the edge case where a prior attempt created the ChangeSpec but died
    before the checkpoint was saved; treat it as already-done to avoid a
    duplicate-name error on retry.
    """
    if wf._method != "create_pull_request":
        return
    if "create_changespec" in cp.completed_steps:
        return
    candidate = cp.cs_name or wf._reserved_name
    if not candidate or not wf._project_file:
        return
    if _changespec_name_in_project_file(wf._project_file, candidate):
        cp.cs_name = candidate
        cp.completed_steps.append("create_changespec")
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


def _is_conflict_state(provider: object, cwd: str) -> bool:
    """Return True when the working tree appears to be in a merge-conflict state."""
    try:
        if provider.is_sync_in_progress(cwd):  # type: ignore[attr-defined]
            return True
    except NotImplementedError:
        pass
    except Exception:
        pass
    try:
        conflicted = provider.get_conflicted_files(cwd)  # type: ignore[attr-defined]
        if conflicted:
            return True
    except NotImplementedError:
        pass
    except Exception:
        pass
    return False
