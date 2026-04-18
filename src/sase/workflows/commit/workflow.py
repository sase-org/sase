"""CommitWorkflow class for dispatching VCS commit operations."""

from __future__ import annotations

import os
from enum import IntEnum

from sase.output import print_status
from sase.telemetry.metrics import VCS_OPERATIONS
from sase.vcs_provider import get_vcs_provider
from sase.workflows.base import BaseWorkflow
from sase.workflows.commit import checkpoint
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
        cp = checkpoint._CommitCheckpoint(
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
        checkpoint.save(cp)

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
            checkpoint.delete()
            return RunResult.FAILED

        cp.dispatch_result = result
        cp.completed_steps.append("dispatch")
        checkpoint.save(cp)

        print_status(f"{self._method} completed successfully!", "success")

        tracking_result = self._run_tracking_steps(cp, result)
        if tracking_result != RunResult.OK:
            return tracking_result

        checkpoint.delete()
        return RunResult.OK

    def _run_tracking_steps(
        self, cp: checkpoint._CommitCheckpoint, result: str | None
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
                    checkpoint.save(cp)
        else:
            cs_name = cp.cs_name

        if "write_result_marker" not in cp.completed_steps:
            write_result_marker(
                self._method, self._payload, self._diff_path, result, cs_name
            )
            cp.completed_steps.append("write_result_marker")
            checkpoint.save(cp)

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
                    checkpoint.save(cp)

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
                checkpoint.save(cp)

        return RunResult.OK


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
