"""CommitWorkflow class for dispatching VCS commit operations."""

import json
import os
import subprocess

from sase.config.core import load_merged_config
from sase.output import print_status
from sase.vcs_provider import get_vcs_provider
from sase.workflows.base import BaseWorkflow

VALID_METHODS = ("create_commit", "create_proposal", "create_pull_request")


class CommitWorkflow(BaseWorkflow):
    """A workflow that dispatches commit operations to VCS provider hooks."""

    def __init__(self, payload: dict, method: str) -> None:
        self._payload = payload
        self._method = method

    @property
    def name(self) -> str:
        return "commit"

    @property
    def description(self) -> str:
        return "Dispatch a VCS commit operation via JSON payload"

    def run(self) -> bool:
        if self._method not in VALID_METHODS:
            print_status(
                f"Unknown commit method '{self._method}'. "
                f"Valid methods: {', '.join(VALID_METHODS)}",
                "error",
            )
            return False

        if not isinstance(self._payload, dict):
            print_status("Payload must be a JSON object.", "error")
            return False
        if "message" not in self._payload and self._method != "create_pull_request":
            print_status("Payload missing required 'message' field.", "error")
            return False
        if self._method == "create_pull_request" and not self._payload.get("name"):
            print_status(
                "Payload missing required 'name' field for create_pull_request.",
                "error",
            )
            return False

        cwd = os.getcwd()

        # Run precommit command (e.g. `just fix`) before any VCS operations
        if not self._run_precommit(cwd):
            return False

        # Bead lifecycle: close, sync, inject ID into commit message
        self._handle_beads(cwd)

        # SASE_PLAN: append PLAN= to message and mark plan as done
        self._handle_sase_plan(cwd)

        # Pre-compute the _<N> suffix for create_pull_request so the CL is
        # created with the correct suffixed name (important for non-git VCS
        # where ChangeSpec creation may not be able to rename the CL later).
        if self._method == "create_pull_request":
            try:
                from sase.workflows.commit.changespec_operations import (
                    compute_suffixed_cl_name,
                )
                from sase.workflows.utils import get_project_from_workspace

                project_name = get_project_from_workspace()
                if project_name:
                    base_name = self._payload["name"]
                    suffixed = compute_suffixed_cl_name(project_name, base_name)
                    if suffixed:
                        self._payload["name"] = suffixed
            except Exception:
                pass  # Best-effort; fall back to unsuffixed name

        provider = get_vcs_provider(cwd)
        dispatch = getattr(provider, self._method)

        print_status(f"Dispatching {self._method} to VCS provider...", "progress")
        ok, result = dispatch(self._payload, cwd)
        if not ok:
            print_status(f"{self._method} failed: {result}", "error")
            return False

        print_status(f"{self._method} completed successfully!", "success")

        cs_name: str | None = None
        if self._method == "create_pull_request":
            cs_name = self._create_changespec(cl_url=result)

        self._write_result_marker(result, cs_name)
        return True

    def _run_precommit(self, cwd: str) -> bool:
        """Run the precommit_command from config, if configured."""
        config = load_merged_config()
        cmd = config.get("precommit_command", "")
        if not cmd:
            return True
        print_status(f"Running precommit command: {cmd}", "progress")
        result = subprocess.run(
            cmd, shell=True, cwd=cwd, check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            print_status(
                f"Precommit command failed (exit {result.returncode}): {cmd}",
                "error",
            )
            return False
        return True

    def _handle_beads(self, cwd: str) -> None:
        """Close and sync beads, inject bead ID into commit message."""
        bead_id = self._payload.get("bead_id")
        has_bead_dir = os.path.isdir(os.path.join(cwd, ".sase_beads")) or os.path.isdir(
            os.path.join(cwd, ".beads")
        )

        if bead_id:
            # Close bead (best effort)
            print_status(f"Closing bead {bead_id}...", "progress")
            subprocess.run(
                ["sase", "bead", "close", bead_id],
                cwd=cwd,
                capture_output=True,
                check=False,
            )
            # Inject bead ID into commit message headline
            message = self._payload.get("message", "")
            if f"({bead_id})" not in message:
                first_line, sep, rest = message.partition("\n")
                self._payload["message"] = f"{first_line} ({bead_id}){sep}{rest}"

        if bead_id or has_bead_dir:
            # Sync beads (best effort)
            subprocess.run(
                ["sase", "bead", "sync"],
                cwd=cwd,
                capture_output=True,
                check=False,
            )

    def _handle_sase_plan(self, cwd: str) -> None:
        """Append PLAN= to commit message and mark plan as done."""
        plan_path = os.environ.get("SASE_PLAN", "")
        if not plan_path or not os.path.isfile(plan_path):
            return

        # Compute repo-root-relative path
        repo_root = ""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                cwd=cwd,
                check=False,
            )
            if result.returncode == 0:
                repo_root = result.stdout.strip()
        except Exception:
            pass

        if repo_root and plan_path.startswith(repo_root + "/"):
            plan_rel = plan_path[len(repo_root) + 1 :]
        elif os.path.isfile(plan_path):
            plan_rel = f".sase/sdd/plans/{os.path.basename(plan_path)}"
        else:
            plan_rel = f"plans/{os.path.basename(plan_path)}"

        # Append PLAN= to commit message
        message = self._payload.get("message", "")
        self._payload["message"] = f"{message}\n\nPLAN={plan_rel}"

        # Mark plan as done
        subprocess.run(
            ["sed", "-i", "s/^status: wip$/status: done/", plan_path],
            check=False,
            capture_output=True,
        )

        # Record plan file for VCS provider to stage
        self._payload["_plan_path"] = plan_path

    def _create_changespec(self, cl_url: str | None) -> str | None:
        """Best-effort ChangeSpec creation after a successful PR flow."""
        try:
            from sase.workflows.utils import (
                get_project_file_path,
                get_project_from_workspace,
            )
            from sase.workspace_provider.changespec import (
                create_changespec_for_workflow,
            )

            project_name = get_project_from_workspace()
            if not project_name:
                print_status(
                    "Skipping ChangeSpec: could not detect project name.", "info"
                )
                return None

            project_file = get_project_file_path(project_name)
            branch_name = self._payload.get("name", "")
            checkout_target = self._payload.get("checkout_target", "HEAD~1")

            cs_name = create_changespec_for_workflow(
                project_name=project_name,
                project_file=project_file,
                checkout_target=checkout_target,
                branch_name=branch_name,
                prompt="",
                response="",
                workflow_name="sase_commit",
                cl_url=cl_url,
                cl_name=self._payload.get("name"),
                commit_description=self._payload.get("message", ""),
            )
            if cs_name:
                print_status(f"Created ChangeSpec: {cs_name}", "success")
            else:
                print_status("Skipping ChangeSpec: no new commits detected.", "info")
            return cs_name
        except Exception as exc:
            print_status(f"Skipping ChangeSpec: {exc}", "warning")
            return None

    def _write_result_marker(
        self, result: str | None, changespec_name: str | None
    ) -> None:
        """Write commit result to a marker file for xprompt post-steps."""
        artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
        if not artifacts_dir:
            return

        marker = {
            "method": self._method,
            "result": result,
            "message": self._payload.get("message", ""),
            "name": self._payload.get("name", ""),
            "bead_id": self._payload.get("bead_id", ""),
            "changespec_name": changespec_name,
        }
        marker_path = os.path.join(artifacts_dir, "commit_result.json")
        with open(marker_path, "w") as f:
            json.dump(marker, f)
