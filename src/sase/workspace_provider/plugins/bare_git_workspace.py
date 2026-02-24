"""Bare-git workspace plugin implementation.

Handles workspace management for git repositories backed by a local bare
remote (i.e. the origin URL is a filesystem path rather than a hosted
service like GitHub).
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sase.ace.changespec import (
    changespec_lock,
    find_all_changespecs,
    write_changespec_atomic,
)
from sase.workspace_provider._hookspec import ResolvedRef, WorkflowMetadata, hookimpl
from sase.workspace_utils import (
    get_default_branch,
    parse_bare_repo_dir,
    parse_workspace_dir,
    set_workspace_dir,
)


def _set_bare_repo_dir(project_file: str, bare_repo_dir: str) -> bool:
    """Set or update the BARE_REPO_DIR field in a .gp project file.

    Creates the file and parent directories if they don't exist.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    try:
        parent_dir = os.path.dirname(project_file)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        if not os.path.exists(project_file):
            with open(project_file, "w", encoding="utf-8") as f:
                f.write(f"BARE_REPO_DIR: {bare_repo_dir}\n")
            return True

        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                content = f.read()

            lines = content.splitlines(keepends=True)
            new_line = f"BARE_REPO_DIR: {bare_repo_dir}\n"

            # Check if BARE_REPO_DIR already exists — update in place
            for i, line in enumerate(lines):
                if line.startswith("BARE_REPO_DIR:"):
                    lines[i] = new_line
                    write_changespec_atomic(
                        project_file,
                        "".join(lines),
                        f"Update BARE_REPO_DIR to {bare_repo_dir}",
                    )
                    return True

            # Insert before first RUNNING: or NAME: line
            insert_idx = len(lines)
            for i, line in enumerate(lines):
                if line.startswith("RUNNING:") or line.startswith("NAME:"):
                    insert_idx = i
                    break

            lines.insert(insert_idx, new_line)
            write_changespec_atomic(
                project_file,
                "".join(lines),
                f"Set BARE_REPO_DIR to {bare_repo_dir}",
            )
            return True
    except Exception:
        return False


@dataclass
class _ResolvedGitRef:
    """Result of resolving a ``#git`` reference."""

    project_file: str
    project_name: str
    primary_workspace_dir: str
    bare_repo_dir: str
    checkout_target: str


def resolve_git_ref(git_ref: str) -> _ResolvedGitRef:
    """Resolve a ``#git`` reference to workspace and branch information.

    Three dispatch modes:

    1. **Project shorthand** (no ``/``, matching project dir): look up
       ``BARE_REPO_DIR`` and ``WORKSPACE_DIR`` from
       ``~/.sase/projects/<name>/<name>.gp``.
    2. **ChangeSpec name**: search all changespecs for a matching name,
       verify project has ``BARE_REPO_DIR``.
    3. **Bare repo path** (contains ``/``): derive project name from path
       basename (strip ``.git``), auto-create ``.gp`` with ``BARE_REPO_DIR``
       and ``WORKSPACE_DIR``.

    Raises:
        ValueError: If the reference cannot be resolved.
    """
    projects_base = Path.home() / ".sase" / "projects"

    # --- Mode 1: project shorthand (no /) ---
    if "/" not in git_ref:
        project_dir = projects_base / git_ref
        project_file_path = project_dir / f"{git_ref}.gp"
        if project_dir.is_dir() and project_file_path.exists():
            bare_repo_dir = parse_bare_repo_dir(str(project_file_path))
            if bare_repo_dir:
                workspace_dir = parse_workspace_dir(str(project_file_path))
                if not workspace_dir:
                    raise ValueError(
                        f"Project '{git_ref}' has BARE_REPO_DIR but "
                        "WORKSPACE_DIR is not set"
                    )
                checkout_target = get_default_branch(workspace_dir)
                return _ResolvedGitRef(
                    project_file=str(project_file_path),
                    project_name=git_ref,
                    primary_workspace_dir=workspace_dir,
                    bare_repo_dir=bare_repo_dir,
                    checkout_target=checkout_target,
                )

        # --- Mode 2: ChangeSpec name ---
        for cs in find_all_changespecs():
            if cs.name == git_ref:
                bare_repo_dir = parse_bare_repo_dir(cs.file_path)
                if not bare_repo_dir:
                    raise ValueError(
                        f"ChangeSpec '{git_ref}' found in {cs.file_path} "
                        "but BARE_REPO_DIR is not set"
                    )
                workspace_dir = parse_workspace_dir(cs.file_path)
                if not workspace_dir:
                    raise ValueError(
                        f"ChangeSpec '{git_ref}' found in {cs.file_path} "
                        "but WORKSPACE_DIR is not set"
                    )
                return _ResolvedGitRef(
                    project_file=cs.file_path,
                    project_name=cs.project_basename,
                    primary_workspace_dir=workspace_dir,
                    bare_repo_dir=bare_repo_dir,
                    checkout_target=f"origin/{git_ref}",
                )

        raise ValueError(f"Cannot resolve git_ref '{git_ref}'")

    # --- Mode 3: bare repo path (contains /) ---
    bare_path = os.path.expanduser(git_ref)
    basename = os.path.basename(bare_path.rstrip("/"))
    project_name = basename[:-4] if basename.endswith(".git") else basename
    if not project_name:
        raise ValueError(f"Cannot derive project name from path '{git_ref}'")

    project_file = str(projects_base / project_name / f"{project_name}.gp")
    clone_dir = str(Path.home() / "projects" / "git" / project_name) + "/"

    _set_bare_repo_dir(project_file, bare_path)
    set_workspace_dir(project_file, clone_dir)
    checkout_target = get_default_branch(clone_dir)

    return _ResolvedGitRef(
        project_file=project_file,
        project_name=project_name,
        primary_workspace_dir=clone_dir,
        bare_repo_dir=bare_path,
        checkout_target=checkout_target,
    )


def init_bare_git_project(
    project_name: str,
    *,
    bare_dir: str | None = None,
    clone_dir: str | None = None,
    existing_bare: str | None = None,
) -> str:
    """Initialize a new bare-repo-backed git project.

    Args:
        project_name: Name of the project.
        bare_dir: Path for the bare repo. Defaults to
            ``~/.sase/repos/<name>.git``.
        clone_dir: Path for the working clone. Defaults to
            ``~/projects/git/<name>/``.
        existing_bare: Path to an existing bare repo to clone from
            instead of creating a new one.

    Returns:
        The path to the created ``.gp`` project file.

    Raises:
        RuntimeError: If git commands fail or existing_bare is not a bare repo.
    """
    if bare_dir is None:
        bare_dir = str(Path.home() / ".sase" / "repos" / f"{project_name}.git")
    if clone_dir is None:
        clone_dir = str(Path.home() / "projects" / "git" / project_name) + "/"

    if existing_bare:
        # Validate it's a bare repo (use --git-dir to avoid
        # safe.bareRepository=explicit blocking access)
        result = subprocess.run(
            ["git", "--git-dir", existing_bare, "rev-parse", "--is-bare-repository"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != "true":
            raise RuntimeError(f"'{existing_bare}' is not a valid bare git repository")
        bare_dir = existing_bare

        # Clone from existing bare
        subprocess.run(
            ["git", "clone", bare_dir, clone_dir],
            capture_output=True,
            text=True,
            check=True,
        )
    else:
        # Create new bare repo
        os.makedirs(bare_dir, exist_ok=True)
        subprocess.run(
            ["git", "init", "--bare", bare_dir],
            capture_output=True,
            text=True,
            check=True,
        )

        # Clone it (will be empty)
        subprocess.run(
            ["git", "clone", bare_dir, clone_dir],
            capture_output=True,
            text=True,
            check=True,
        )

        # Set default git identity for the initial commit
        subprocess.run(
            ["git", "config", "user.email", "sase@localhost"],
            cwd=clone_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "sase"],
            cwd=clone_dir,
            capture_output=True,
            check=True,
        )

        # Create initial commit and push
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "Initial commit"],
            cwd=clone_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "push", "origin", "HEAD"],
            cwd=clone_dir,
            capture_output=True,
            text=True,
            check=True,
        )

    # Create .gp project file
    projects_base = Path.home() / ".sase" / "projects"
    project_file = str(projects_base / project_name / f"{project_name}.gp")

    _set_bare_repo_dir(project_file, bare_dir)
    set_workspace_dir(project_file, clone_dir)

    return project_file


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
        return _submit_bare_git(
            changespec_file, changespec_name, project_basename, console
        )

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


def _submit_bare_git(
    changespec_file: str,
    changespec_name: str,
    project_basename: str,
    console: object | None,
) -> tuple[bool, str | None]:
    """Submit a bare-git ChangeSpec by merging its branch to the default branch.

    After merging, renames the ChangeSpec with a timestamp suffix and
    transitions its status to Submitted.
    """
    from rich.console import Console
    from rich.markup import escape as escape_markup

    from sase.ace.changespec import find_all_changespecs
    from sase.ace.hooks.processes import kill_and_persist_all_running_processes
    from sase.ace.operations import has_active_children
    from sase.running_field import (
        claim_workspace,
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
        release_workspace,
    )
    from sase.vcs_provider import get_vcs_provider
    from sase.workspace_utils import get_default_branch

    rich_console: Console | None = console if isinstance(console, Console) else None

    # Find the ChangeSpec object for process/children checks
    all_changespecs = find_all_changespecs()
    changespec = None
    for cs in all_changespecs:
        if cs.name == changespec_name:
            changespec = cs
            break
    if changespec is None:
        return (False, f"ChangeSpec '{changespec_name}' not found")

    # Kill any running processes before submitting
    log_fn = (
        (lambda msg: rich_console.print(f"[cyan]{escape_markup(msg)}[/cyan]"))
        if rich_console
        else None
    )
    kill_and_persist_all_running_processes(
        changespec,
        changespec_file,
        changespec_name,
        "Killed hook running on submitted CL.",
        log_fn=log_fn,
    )

    # Validate no active children
    if has_active_children(
        changespec,
        all_changespecs,
        terminal_statuses=("Submitted", "Reverted", "Archived"),
    ):
        return (
            False,
            "Cannot submit: other ChangeSpecs have this one as their parent "
            "and are not Submitted, Reverted, or Archived",
        )

    # Get workspace info
    workspace_dir = parse_workspace_dir(changespec_file)
    if not workspace_dir:
        return (False, "WORKSPACE_DIR is not set for this project")

    # Claim a workspace >= 100 for the submit operation
    workspace_num = get_first_available_axe_workspace(changespec_file)
    workflow_name = f"submit-{changespec_name}"
    pid = os.getpid()

    try:
        ws_dir, _ = get_workspace_directory_for_num(workspace_num, project_basename)
    except RuntimeError as e:
        return (False, f"Failed to get workspace directory: {e}")

    if rich_console:
        rich_console.print(f"[cyan]Claiming workspace #{workspace_num}[/cyan]")

    if not claim_workspace(
        changespec_file, workspace_num, workflow_name, pid, changespec_name
    ):
        return (False, f"Failed to claim workspace #{workspace_num}")

    try:
        # Checkout the branch
        if rich_console:
            rich_console.print(
                f"[cyan]Checking out {escape_markup(changespec_name)}...[/cyan]"
            )

        provider = get_vcs_provider(ws_dir)
        branch_name = provider.resolve_revision(
            changespec_name, project_basename, ws_dir
        )
        success, error = provider.checkout(branch_name, ws_dir)
        if not success:
            return (False, f"Failed to checkout branch: {error}")

        # Get default branch
        default_branch_ref = get_default_branch(ws_dir)
        default_branch = default_branch_ref.rsplit("/", 1)[-1]

        if rich_console:
            rich_console.print(
                f"[cyan]Merging {escape_markup(changespec_name)} into {escape_markup(default_branch)}...[/cyan]"
            )

        # Bare git: local merge + push
        return _submit_via_local_merge(
            changespec_file,
            changespec_name,
            project_basename,
            ws_dir,
            default_branch,
            provider,
            rich_console,
        )

    finally:
        release_workspace(
            changespec_file,
            workspace_num,
            workflow_name,
            changespec_name,
        )
        if rich_console:
            rich_console.print(f"[cyan]Released workspace #{workspace_num}[/cyan]")


def _submit_via_local_merge(
    changespec_file: str,
    changespec_name: str,
    project_basename: str,
    ws_dir: str,
    default_branch: str,
    provider: object,
    console: object | None,
) -> tuple[bool, str | None]:
    """Submit by performing a local merge to the default branch.

    Checks out the default branch in ``ws_dir``, merges the feature branch,
    pushes, and cleans up the branch locally and remotely.
    """
    from rich.console import Console
    from rich.markup import escape as escape_markup

    from sase.submission_utils import finalize_submission

    rich_console: Console | None = console if isinstance(console, Console) else None

    branch_name = provider.resolve_revision(  # type: ignore[attr-defined]
        changespec_name, project_basename, ws_dir
    )

    # Checkout the default branch, then merge the feature branch
    subprocess.run(
        ["git", "checkout", default_branch],
        cwd=ws_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    result = subprocess.run(
        ["git", "merge", branch_name],
        cwd=ws_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # Abort the merge on conflict
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=ws_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        return (False, f"Merge conflict merging {branch_name} into {default_branch}")

    if rich_console:
        rich_console.print(
            f"[green]Merged {escape_markup(branch_name)} into {escape_markup(default_branch)}[/green]"
        )

    # Push
    result = subprocess.run(
        ["git", "push"],
        cwd=ws_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return (False, f"git push failed: {result.stderr.strip()}")

    if rich_console:
        rich_console.print("[green]Pushed to remote[/green]")

    # Delete local branch
    subprocess.run(
        ["git", "branch", "-d", branch_name],
        cwd=ws_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    # Delete remote branch
    subprocess.run(
        ["git", "push", "origin", "--delete", branch_name],
        cwd=ws_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    if rich_console:
        rich_console.print(
            f"[green]Deleted branch {escape_markup(branch_name)}[/green]"
        )

    return finalize_submission(changespec_file, changespec_name, rich_console)
