"""Bare-git workspace plugin implementation.

Handles workspace management for git repositories backed by a local bare
remote (i.e. the origin URL is a filesystem path rather than a hosted
service like GitHub).
"""

import os
import subprocess

from sase.workspace_provider._hookspec import ResolvedRef, WorkflowMetadata, hookimpl
from sase.workspace_utils import parse_workspace_dir


class BareGitWorkspacePlugin:
    """Pluggy plugin for bare-git workspace management."""

    def _is_bare_git_project(self, project_file: str) -> bool:
        """Check if *project_file* represents a bare-git project."""
        workspace_dir = parse_workspace_dir(project_file)
        if not workspace_dir or not os.path.isdir(os.path.join(workspace_dir, ".git")):
            return False

        # Lazy import to avoid circular dependency
        from sase.git_workspace import parse_bare_repo_dir

        if parse_bare_repo_dir(project_file):
            return True

        # Check origin remote URL — local path means bare git
        try:
            result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                check=False,
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
            ref_pattern=r"(?:^|(?<=\s))#git(?::([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="Git (bare)",
            pre_allocated_env_prefix="SASE_GIT",
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
        from sase.git_workspace import resolve_git_ref

        resolved = resolve_git_ref(ref)
        return ResolvedRef(
            project_file=resolved.project_file,
            project_name=resolved.project_name,
            primary_workspace_dir=resolved.primary_workspace_dir,
            checkout_target=resolved.checkout_target,
            extra={"bare_repo_dir": resolved.bare_repo_dir},
        )

    @hookimpl
    def ws_submit(
        self,
        changespec_file: str,
        changespec_name: str,
        project_basename: str,
        console: object | None,
    ) -> tuple[bool, str | None] | None:
        if not self._is_bare_git_project(changespec_file):
            return None
        # Delegate to existing submission logic
        from sase.ace.changespec import find_all_changespecs
        from sase.git_submit import submit_git_changespec

        for cs in find_all_changespecs():
            if cs.name == changespec_name:
                return submit_git_changespec(cs, console)  # type: ignore[arg-type]
        return (False, f"ChangeSpec '{changespec_name}' not found")

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
        from sase.workspace_utils import ensure_git_clone

        return ensure_git_clone(primary_workspace_dir, workspace_num)

    @hookimpl
    def ws_prepare_mail(
        self,
        changespec_name: str,
        changespec_parent: str | None,
        project_basename: str,
        project_file: str,
        target_dir: str,
        console: object | None,
    ) -> object | None:
        if not self._is_bare_git_project(project_file):
            return None
        return _prepare_mail_git(changespec_name, project_basename, target_dir, console)

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


def _prepare_mail_git(
    changespec_name: str,
    project_basename: str,
    target_dir: str,
    console: object | None,
) -> object | None:
    """Git-specific mail preparation: display branch info and confirm push."""
    from rich.console import Console
    from rich.markup import escape as escape_markup
    from rich.panel import Panel

    from sase.ace.mail_ops import MailPrepResult, get_cl_description
    from sase.vcs_provider import get_vcs_provider

    if not isinstance(console, Console):
        return None

    provider = get_vcs_provider(target_dir)

    # Display current branch name
    branch_ok, branch_name = provider.get_branch_name(target_dir)
    if branch_ok and branch_name:
        console.print(f"\n[cyan]Branch: {branch_name}[/cyan]")

    # Display current description
    success, current_desc = get_cl_description(
        changespec_name,
        target_dir,
        console,
        project_basename=project_basename,
    )
    if success and current_desc:
        console.print(
            Panel(
                escape_markup(current_desc.rstrip()),
                title="Commit Description",
                border_style="cyan",
                padding=(1, 2),
            )
        )

    # Prompt user before pushing
    console.print(
        "\n[cyan]Do you want to push and create/update the PR now? (y/n):[/cyan] ",
        end="",
    )
    try:
        mail_response = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Aborted[/yellow]")
        return None

    should_mail = mail_response in ["y", "yes"]
    if not should_mail:
        console.print("[yellow]User declined to push[/yellow]")

    return MailPrepResult(should_mail=should_mail)
