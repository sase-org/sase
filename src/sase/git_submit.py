"""Git/GitHub submission logic for ChangeSpecs (Mailed → Submitted)."""

import os
import subprocess

from rich.console import Console
from rich.markup import escape as escape_markup

from sase.ace.changespec import ChangeSpec, find_all_changespecs
from sase.ace.hooks.processes import kill_and_persist_all_running_processes
from sase.ace.operations import (
    has_active_children,
    rename_changespec_with_references,
)
from sase.gh_workspace import (
    detect_workflow_type_for_project,
    get_default_branch,
    parse_workspace_dir,
)
from sase.running_field import (
    claim_workspace,
    get_first_available_axe_workspace,
    get_workspace_directory_for_num,
    release_workspace,
)
from sase.sase_utils import generate_timestamp
from sase.vcs_provider import VCSProvider, get_vcs_provider
from sase.status_state_machine import transition_changespec_status


def submit_git_changespec(
    changespec: ChangeSpec,
    console: Console | None = None,
) -> tuple[bool, str | None]:
    """Submit a git/gh ChangeSpec by merging its branch to the default branch.

    For GitHub projects with an existing PR, uses ``gh pr merge``.
    For bare git or GitHub without a PR, performs a local merge and push.

    After merging, renames the ChangeSpec with a timestamp suffix and
    transitions its status to Submitted.

    Args:
        changespec: The ChangeSpec to submit.
        console: Optional Rich Console for output.

    Returns:
        Tuple of (success, error_message).
    """
    # Kill any running processes before submitting
    log_fn = (
        (lambda msg: console.print(f"[cyan]{escape_markup(msg)}[/cyan]"))
        if console
        else None
    )
    kill_and_persist_all_running_processes(
        changespec,
        changespec.file_path,
        changespec.name,
        "Killed hook running on submitted CL.",
        log_fn=log_fn,
    )

    # Validate no active children
    all_changespecs = find_all_changespecs()
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
    workspace_dir = parse_workspace_dir(changespec.file_path)
    if not workspace_dir:
        return (False, "WORKSPACE_DIR is not set for this project")

    # Detect workflow type
    vcs_type = detect_workflow_type_for_project(changespec.file_path)
    if vcs_type == "hg":
        return (False, "hg submission has its own path; use that instead")

    project_basename = os.path.basename(changespec.file_path).replace(".gp", "")

    # Claim a workspace >= 100 for the submit operation
    workspace_num = get_first_available_axe_workspace(changespec.file_path)
    workflow_name = f"submit-{changespec.name}"
    pid = os.getpid()

    try:
        ws_dir, _ = get_workspace_directory_for_num(workspace_num, project_basename)
    except RuntimeError as e:
        return (False, f"Failed to get workspace directory: {e}")

    if console:
        console.print(f"[cyan]Claiming workspace #{workspace_num}[/cyan]")

    if not claim_workspace(
        changespec.file_path, workspace_num, workflow_name, pid, changespec.name
    ):
        return (False, f"Failed to claim workspace #{workspace_num}")

    try:
        # Checkout the branch
        if console:
            console.print(
                f"[cyan]Checking out {escape_markup(changespec.name)}...[/cyan]"
            )

        provider = get_vcs_provider(ws_dir)
        branch_name = provider.resolve_revision(
            changespec.name, changespec.project_basename, ws_dir
        )
        success, error = provider.checkout(branch_name, ws_dir)
        if not success:
            return (False, f"Failed to checkout branch: {error}")

        # Get default branch
        default_branch_ref = get_default_branch(ws_dir)
        default_branch = default_branch_ref.rsplit("/", 1)[-1]

        if console:
            console.print(
                f"[cyan]Merging {escape_markup(changespec.name)} into {escape_markup(default_branch)}...[/cyan]"
            )

        # Check if this is a GitHub project with an existing PR
        if vcs_type == "gh":
            has_pr = _check_existing_pr(ws_dir)
            if has_pr:
                return _submit_via_pr_merge(changespec, ws_dir, console)
            return (
                False,
                "GitHub project has no PR for this branch. Create a PR first with #pr.",
            )

        # Bare git: local merge + push
        return _submit_via_local_merge(
            changespec, ws_dir, default_branch, provider, console
        )

    finally:
        release_workspace(
            changespec.file_path,
            workspace_num,
            workflow_name,
            changespec.name,
        )
        if console:
            console.print(f"[cyan]Released workspace #{workspace_num}[/cyan]")


def _check_existing_pr(cwd: str) -> bool:
    """Check if a PR exists for the current branch."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", "--json", "number"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _submit_via_pr_merge(
    changespec: ChangeSpec,
    ws_dir: str,
    console: Console | None,
) -> tuple[bool, str | None]:
    """Submit by merging the PR via ``gh pr merge``."""
    from sase.github_config import get_github_username

    username = get_github_username()
    if not username:
        return (
            False,
            "Cannot submit GitHub PR: 'github_username' is not configured in sase.yml. "
            "Add 'github_username: <your_username>' to ~/.config/sase/sase.yml",
        )

    if console:
        console.print("[cyan]Merging PR via gh pr merge...[/cyan]")

    try:
        result = subprocess.run(
            ["gh", "pr", "merge", "--merge", "--delete-branch"],
            cwd=ws_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            return (
                False,
                f"gh pr merge failed: {error_msg}"
                if error_msg
                else "gh pr merge failed",
            )
    except FileNotFoundError:
        return (False, "gh command not found")

    if console:
        console.print("[green]PR merged successfully[/green]")

    return _finalize_submission(changespec, console)


def _submit_via_local_merge(
    changespec: ChangeSpec,
    ws_dir: str,
    default_branch: str,
    provider: VCSProvider,
    console: Console | None,
) -> tuple[bool, str | None]:
    """Submit by performing a local merge to the default branch.

    Checks out the default branch in ``ws_dir``, merges the feature branch,
    pushes, and cleans up the branch locally and remotely.
    """
    branch_name = provider.resolve_revision(
        changespec.name, changespec.project_basename, ws_dir
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

    if console:
        console.print(
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

    if console:
        console.print("[green]Pushed to remote[/green]")

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

    if console:
        console.print(f"[green]Deleted branch {escape_markup(branch_name)}[/green]")

    return _finalize_submission(changespec, console)


def _finalize_submission(
    changespec: ChangeSpec,
    console: Console | None,
) -> tuple[bool, str | None]:
    """Rename ChangeSpec with timestamp and transition to Submitted."""
    timestamp = generate_timestamp()
    new_name = f"{changespec.name}__{timestamp}"

    if console:
        console.print(f"[cyan]Renaming ChangeSpec to: {escape_markup(new_name)}[/cyan]")

    try:
        rename_changespec_with_references(
            changespec.file_path, changespec.name, new_name
        )
    except Exception as e:
        return (False, f"Failed to rename ChangeSpec: {e}")

    if console:
        console.print(
            f"[green]Renamed ChangeSpec: {escape_markup(changespec.name)} -> {escape_markup(new_name)}[/green]"
        )

    # Transition status to Submitted
    success, _, error, _ = transition_changespec_status(
        changespec.file_path,
        new_name,
        "Submitted",
        validate=False,
    )
    if not success:
        return (False, f"Failed to update status: {error}")

    if console:
        console.print("[green]Status updated to Submitted[/green]")

    return (True, None)
