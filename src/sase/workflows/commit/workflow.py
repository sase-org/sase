"""CommitWorkflow class for dispatching VCS commit operations."""

import os

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
        provider = get_vcs_provider(cwd)
        dispatch = getattr(provider, self._method)

        print_status(f"Dispatching {self._method} to VCS provider...", "progress")
        ok, result = dispatch(self._payload, cwd)
        if not ok:
            print_status(f"{self._method} failed: {result}", "error")
            return False

        print_status(f"{self._method} completed successfully!", "success")

        if self._method == "create_pull_request":
            self._create_changespec(cl_url=result)

        return True

    def _create_changespec(self, cl_url: str | None) -> None:
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
                return

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
            )
            if cs_name:
                print_status(f"Created ChangeSpec: {cs_name}", "success")
            else:
                print_status("Skipping ChangeSpec: no new commits detected.", "info")
        except Exception as exc:
            print_status(f"Skipping ChangeSpec: {exc}", "warning")
