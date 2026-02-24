"""Workspace plugin manager that delegates to pluggy hooks."""

import pluggy

from ._hookspec import ResolvedRef, WorkflowMetadata


class WorkspacePluginManager:
    """Wraps a :class:`pluggy.PluginManager` and delegates to workspace hooks.

    Unlike the VCS plugin manager (which wraps a single plugin), this
    manager has ALL workspace plugins registered.  Pluggy's
    ``firstresult=True`` semantics ensure the first plugin that returns
    a non-``None`` value wins.
    """

    def __init__(self, pm: pluggy.PluginManager) -> None:
        self._pm = pm

    def get_workflow_metadata(self) -> list[WorkflowMetadata]:
        results: list[WorkflowMetadata | None] = (
            self._pm.hook.ws_get_workflow_metadata()
        )
        return [r for r in results if r is not None]

    def detect_workflow_type(self, project_file: str) -> str | None:
        return self._pm.hook.ws_detect_workflow_type(  # type: ignore[no-any-return]
            project_file=project_file
        )

    def get_change_label(self, project_file: str) -> str | None:
        return self._pm.hook.ws_get_change_label(  # type: ignore[no-any-return]
            project_file=project_file
        )

    def resolve_ref(self, ref: str, workflow_type: str) -> ResolvedRef | None:
        return self._pm.hook.ws_resolve_ref(  # type: ignore[no-any-return]
            ref=ref, workflow_type=workflow_type
        )

    def submit(
        self,
        changespec_file: str,
        changespec_name: str,
        project_basename: str,
        console: object | None = None,
    ) -> tuple[bool, str | None] | None:
        return self._pm.hook.ws_submit(  # type: ignore[no-any-return]
            changespec_file=changespec_file,
            changespec_name=changespec_name,
            project_basename=project_basename,
            console=console,
        )

    def setup_workflow(
        self,
        ref: str,
        workflow_type: str,
        n: int,
        release: bool,
    ) -> dict[str, str] | None:
        return self._pm.hook.ws_setup_workflow(  # type: ignore[no-any-return]
            ref=ref, workflow_type=workflow_type, n=n, release=release
        )

    def extract_change_identifier(self, cl_url: str) -> tuple[str, str] | None:
        return self._pm.hook.ws_extract_change_identifier(  # type: ignore[no-any-return]
            cl_url=cl_url
        )

    def generate_submitted_check_script(
        self, identifier: str, vcs_type: str
    ) -> str | None:
        return self._pm.hook.ws_generate_submitted_check_script(  # type: ignore[no-any-return]
            identifier=identifier, vcs_type=vcs_type
        )

    def supports_reviewer_comments(self, cl_url: str) -> bool | None:
        return self._pm.hook.ws_supports_reviewer_comments(  # type: ignore[no-any-return]
            cl_url=cl_url
        )

    def generate_reviewer_comments_script(self, changespec_name: str) -> str | None:
        return self._pm.hook.ws_generate_reviewer_comments_script(  # type: ignore[no-any-return]
            changespec_name=changespec_name
        )
