"""Directory workspace plugin for the built-in ``#cd`` workflow."""

from __future__ import annotations

import os
from pathlib import Path

from sase.workspace_provider._hookspec import ResolvedRef, WorkflowMetadata, hookimpl

HOME_PROJECT_FILE = "~/.sase/projects/home/home.gp"


def _home_project_file() -> str:
    return os.path.expanduser(HOME_PROJECT_FILE)


def _expand_cd_ref(ref: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(ref))
    return Path(expanded).resolve()


def _project_name_for_path(path: Path) -> str:
    if path == Path.home().resolve():
        return "home"
    return path.name or str(path)


class CdWorkspacePlugin:
    """Pluggy plugin for directory/no-VCS workspace references."""

    @hookimpl
    def ws_get_workflow_metadata(self) -> WorkflowMetadata | None:
        return WorkflowMetadata(
            workflow_type="cd",
            ref_pattern=r"(?:^|(?<=\s))#cd(?:[_:]([^\s()]+)|\(([^)]*)\))",
            display_name="Directory",
            pre_allocated_env_prefix="SASE_CD",
        )

    @hookimpl
    def ws_resolve_ref(self, ref: str, workflow_type: str) -> ResolvedRef | None:
        if workflow_type != "cd":
            return None

        target = _expand_cd_ref(ref)
        if not target.exists():
            raise ValueError(f"Directory does not exist: {target}")
        if not target.is_dir():
            raise ValueError(f"Path is not a directory: {target}")

        target_str = str(target)
        return ResolvedRef(
            project_file=_home_project_file(),
            project_name=_project_name_for_path(target),
            primary_workspace_dir=target_str,
            checkout_target=target_str,
        )

    @hookimpl
    def ws_get_workspace_directory(
        self,
        workflow_type: str,
        workspace_num: int,
        project_name: str,
        primary_workspace_dir: str,
    ) -> str | None:
        if workflow_type != "cd":
            return None
        return primary_workspace_dir
