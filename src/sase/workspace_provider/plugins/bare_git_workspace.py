"""Bare-git workspace plugin implementation.

Handles workspace management for git repositories backed by a local bare
remote (i.e. the origin URL is a filesystem path rather than a hosted
service like GitHub).
"""

import os
import re
import subprocess

from sase.core.paths import is_valid_sase_project_name
from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider._hookspec import ResolvedRef, WorkflowMetadata, hookimpl
from sase.workspace_provider.plugins.bare_git_ref import (
    ResolvedGitRef,
    resolve_git_ref,
    set_bare_repo_dir,
)
from sase.workspace_provider.plugins.bare_git_init import init_bare_git_project
from sase.workspace_provider.plugins.bare_git_submit import (
    prepare_mail_git,
    submit_bare_git,
)
from sase.workspace_provider.utils import (
    parse_bare_repo_dir,
    parse_workspace_dir,
)

# Re-export for backwards compatibility with external imports
__all__ = [
    "BareGitWorkspacePlugin",
    "ResolvedGitRef",
    "init_bare_git_project",
    "resolve_git_ref",
    "set_bare_repo_dir",
]


def _valid_project_name_from_git_name(name: str) -> str | None:
    project_name = re.sub(r"_\d+$", "", name)
    if not is_valid_sase_project_name(project_name):
        return None
    return project_name


def _run_git(args: list[str], *, cwd: str) -> subprocess.CompletedProcess[str]:
    result, _ = run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        ),
        cwd=cwd,
    )
    return result


class BareGitWorkspacePlugin:
    """Pluggy plugin for bare-git workspace management."""

    def _is_bare_git_project(self, project_file: str) -> bool:
        """Check if *project_file* represents a bare-git project."""
        workspace_dir = parse_workspace_dir(project_file)
        if not workspace_dir or not os.path.isdir(os.path.join(workspace_dir, ".git")):
            return False

        if parse_bare_repo_dir(project_file):
            return True

        # Check origin remote URL — local path means bare git
        try:
            result = _run_git(
                ["config", "--get", "remote.origin.url"],
                cwd=workspace_dir,
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                if url and not url.startswith(
                    ("http://", "https://", "git@", "ssh://")
                ):
                    return True
        except Exception:
            pass

        return False

    @hookimpl
    def ws_get_workflow_metadata(self) -> WorkflowMetadata | None:
        return WorkflowMetadata(
            workflow_type="git",
            ref_pattern=r"(?:^|(?<=\s))#git(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="Git (bare)",
            pre_allocated_env_prefix="SASE_GIT",
            vcs_family="git",
            vcs_provider_name="bare_git",
            sdd_storage_policy="in_tree",
        )

    @hookimpl
    def ws_detect_workflow_type(self, project_file: str) -> str | None:
        if self._is_bare_git_project(project_file):
            return "git"
        return None

    @hookimpl
    def ws_get_change_label(self, project_file: str) -> str | None:
        if self._is_bare_git_project(project_file):
            return "PR"
        return None

    @hookimpl
    def ws_resolve_ref(self, ref: str, workflow_type: str) -> ResolvedRef | None:
        if workflow_type != "git":
            return None
        resolved = resolve_git_ref(ref)
        return ResolvedRef(
            project_file=resolved.project_file,
            project_name=resolved.project_name,
            primary_workspace_dir=resolved.primary_workspace_dir,
            checkout_target=resolved.checkout_target,
            extra={"bare_repo_dir": resolved.bare_repo_dir},
            canonical_ref=resolved.project_name if "/" in ref else None,
        )

    @hookimpl
    def ws_submit(
        self,
        patch_file: str,
        changespec_name: str,
        project_basename: str,
        console: object | None,
    ) -> tuple[bool, str | None] | None:
        if not self._is_bare_git_project(patch_file):
            return None
        return submit_bare_git(patch_file, changespec_name, project_basename, console)

    @hookimpl
    def ws_setup_workflow(
        self,
        ref: str,
        workflow_type: str,
        n: int,
        release: bool,
    ) -> dict[str, str] | None:
        if workflow_type != "git":
            return None
        # Setup logic will be expanded in later phases
        return None

    @hookimpl
    def ws_get_workspace_directory(
        self,
        workflow_type: str,
        workspace_num: int,
        project_name: str,
        primary_workspace_dir: str,
    ) -> str | None:
        if workflow_type != "git":
            return None
        from sase.workspace_provider.utils import ensure_workspace_checkout
        from sase.sdd.files import ensure_bare_git_sdd_initialized

        ensure_bare_git_sdd_initialized(
            primary_workspace_dir,
            commit=True,
            push=True,
            raise_on_error=True,
        )

        return ensure_workspace_checkout(primary_workspace_dir, workspace_num)

    @hookimpl
    def ws_prepare_mail(
        self,
        changespec_name: str,
        patch_parent: str | None,
        project_basename: str,
        project_file: str,
        target_dir: str,
        console: object | None,
    ) -> object | None:
        if not self._is_bare_git_project(project_file):
            return None
        return prepare_mail_git(changespec_name, project_basename, target_dir, console)

    @hookimpl
    def ws_get_workspace_name(self, cwd: str) -> str | None:
        cwd = os.path.abspath(cwd)
        # Try git remote origin URL first
        try:
            result = _run_git(
                ["config", "--get", "remote.origin.url"],
                cwd=cwd,
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                if url:
                    name = os.path.basename(url)
                    if name.endswith(".git"):
                        name = name[:-4]
                    if name:
                        project_name = _valid_project_name_from_git_name(name)
                        if project_name is not None:
                            return project_name
        except Exception:
            pass

        # Fall back to repo root basename
        try:
            result = _run_git(
                ["rev-parse", "--show-toplevel"],
                cwd=cwd,
            )
            if result.returncode == 0:
                name = os.path.basename(result.stdout.strip())
                if name:
                    return _valid_project_name_from_git_name(name)
        except Exception:
            pass

        return None

    @hookimpl
    def ws_format_commit_description(
        self,
        file_path: str,
        project: str,
        workflow_type: str,
        bug: str | None,
        fixed_bug: str | None,
    ) -> bool | None:
        if workflow_type != "git":
            return None
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"[{project}] {content}\n")
        return True
