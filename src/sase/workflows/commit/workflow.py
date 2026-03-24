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

        cwd = os.getcwd()
        provider = get_vcs_provider(cwd)
        dispatch = getattr(provider, self._method)

        print_status(f"Dispatching {self._method} to VCS provider...", "progress")
        ok, err = dispatch(self._payload, cwd)
        if not ok:
            print_status(f"{self._method} failed: {err}", "error")
            return False

        print_status(f"{self._method} completed successfully!", "success")
        return True
