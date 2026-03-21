"""Bare-git submission and mail-preparation operations.

Handles merging feature branches back to the default branch (submit) and
prompting users before push (mail).
"""

import os
import subprocess

from sase.workspace_provider.utils import (
    get_default_branch,
    parse_workspace_dir,
)


def prepare_mail_git(
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


def submit_bare_git(
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

        # Fetch from remote and create a local branch so checkout can find it.
        # Using the refspec "src:dst" form ensures a local ref is created,
        # rather than just updating FETCH_HEAD.
        subprocess.run(
            ["git", "fetch", "origin", f"+{branch_name}:{branch_name}"],
            cwd=ws_dir,
            capture_output=True,
            text=True,
            check=False,
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

    from sase.workspace_provider.submission_utils import finalize_submission

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
