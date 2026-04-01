"""Handler for the reword tool action."""

import os
import re
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from rich.markup import escape as _esc

from sase.workflows.commit_utils import run_sase_hg_clean
from sase.workflows.commit.editor_utils import get_editor
from sase.vcs_provider import get_vcs_provider

from ..changespec import ChangeSpec

if TYPE_CHECKING:
    from rich.console import Console

    from ..tui._workflow_context import WorkflowContext


def _sync_description_bg(workspace_dir: str, file_path: str, name: str) -> None:
    """Sync the ChangeSpec DESCRIPTION field after a successful reword.

    Runs ``get_description`` to get the clean description from the commit
    message and writes it back to the ``.gp`` file.  Uses ``print()`` instead
    of Rich console since this runs in a background task with captured stdout.

    Args:
        workspace_dir: Path to the workspace directory.
        file_path: Path to the project file.
        name: The ChangeSpec name.
    """
    from sase.status_state_machine import update_changespec_description_atomic
    from sase.vcs_provider.config import strip_project_pr_prefix, strip_pr_tags

    provider = get_vcs_provider(workspace_dir)
    success, desc_output = provider.get_description("", workspace_dir, short=True)
    if not success:
        print(f"Warning: could not read updated description: {desc_output}")
        return

    new_description = strip_pr_tags(desc_output.strip()) if desc_output else ""
    new_description = strip_project_pr_prefix(new_description)
    if not new_description:
        print("Warning: cl_desc -s returned empty output, skipping DESCRIPTION sync")
        return

    success = update_changespec_description_atomic(file_path, name, new_description)
    if success:
        print("Synced DESCRIPTION to project file")
    else:
        print("Warning: failed to sync DESCRIPTION to project file")


def _fetch_cl_description(
    project_basename: str, changespec_name: str, console: "Console"
) -> str | None:
    """Fetch the CL description from the primary workspace without claiming it.

    Gets the primary workspace (#1) and runs ``cl_desc -r <name>`` to retrieve
    the current commit description.

    Args:
        project_basename: The project basename for workspace lookup.
        changespec_name: The changespec name (revision) to fetch.
        console: Rich console for output.

    Returns:
        The description string, or None on failure.
    """
    from sase.running_field import get_workspace_directory as get_primary_workspace

    try:
        target_dir = get_primary_workspace(project_basename, 1)
    except RuntimeError as e:
        console.print(f"[red]Error getting workspace: {_esc(str(e))}[/red]")
        return None

    provider = get_vcs_provider(target_dir)
    resolved = provider.resolve_revision(changespec_name, project_basename, target_dir)
    success, description = provider.get_description(resolved, target_dir)
    if not success:
        console.print(f"[red]{_esc(str(description))}[/red]")
        return None
    return description


def _add_prettier_ignore_before_tags(description: str) -> str:
    """Insert ``<!-- prettier-ignore -->`` before the contiguous CL tag block.

    The tag block is the contiguous run of ``KEY=value`` / ``Key: value``
    lines at the very end of *description* (blank trailing lines are
    skipped first).  If no tag block is found the description is returned
    unchanged.
    """
    lines = description.split("\n")
    tag_pattern = re.compile(r"^[A-Z][A-Z0-9_]*=")

    # Skip trailing blank lines
    last_non_blank = len(lines) - 1
    while last_non_blank >= 0 and lines[last_non_blank].strip() == "":
        last_non_blank -= 1

    # Scan upward to find contiguous tag block
    tags_start_idx = len(lines)
    for idx in range(last_non_blank, -1, -1):
        if tag_pattern.match(lines[idx].strip()):
            tags_start_idx = idx
        else:
            break

    if tags_start_idx >= len(lines):
        return description

    # Insert prettier-ignore comment before the tag block
    before = lines[:tags_start_idx]
    after = lines[tags_start_idx:]
    return "\n".join(before + ["<!-- prettier-ignore -->"] + after)


def _strip_prettier_ignore(content: str) -> str:
    """Remove any ``<!-- prettier-ignore -->`` lines from *content*."""
    lines = content.split("\n")
    filtered = [line for line in lines if line.strip() != "<!-- prettier-ignore -->"]
    return "\n".join(filtered)


def _open_editor_with_content(content: str, console: "Console") -> str | None:
    """Open the user's editor with initial content and return the edited result.

    Creates a temporary file, writes *content* to it, opens the editor, reads
    back the (possibly modified) content, and cleans up the temp file.

    Args:
        content: Initial text to populate the editor with.
        console: Rich console for output.

    Returns:
        The edited content string, or None if the editor failed.
    """
    from sase.core.paths import get_sase_tmpdir

    fd, temp_path = tempfile.mkstemp(
        suffix=".md", prefix="sase_reword_", dir=get_sase_tmpdir()
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        console.print(f"[red]Failed to write temp file: {_esc(str(e))}[/red]")
        os.close(fd)
        return None

    editor = get_editor()

    try:
        result = subprocess.run([editor, temp_path], check=False)
        if result.returncode != 0:
            console.print("[red]Editor exited with non-zero status.[/red]")
            return None

        with open(temp_path, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        console.print(f"[red]Failed to open editor: {_esc(str(e))}[/red]")
        return None
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def add_tag_task(
    changespec_name: str,
    changespec_file_path: str,
    project_basename: str,
    tag_name: str,
    tag_value: str,
) -> tuple[bool, str]:
    """Execute add-tag as a background task.

    Claims a workspace, checks out the CL, runs sase_hg_reword --add-tag,
    and releases the workspace in a finally block.

    Returns:
        Tuple of (success, message).
    """
    from sase.running_field import (
        claim_workspace,
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
        release_workspace,
    )

    workspace_num = get_first_available_axe_workspace(changespec_file_path)
    workflow_name = f"add_tag-{changespec_name}"

    try:
        workspace_dir, workspace_suffix = get_workspace_directory_for_num(
            workspace_num, project_basename
        )
    except RuntimeError as e:
        return (False, f"Failed to get workspace directory: {e}")

    pid = os.getpid()
    if not claim_workspace(
        changespec_file_path, workspace_num, workflow_name, pid, changespec_name
    ):
        return (False, "Failed to claim workspace")

    try:
        if workspace_suffix:
            print(f"Using workspace: {workspace_suffix}")

        # Clean workspace before switching branches
        clean_success, clean_error = run_sase_hg_clean(
            workspace_dir, f"{changespec_name}-add_tag"
        )
        if not clean_success:
            print(f"Warning: sase_hg_clean failed: {clean_error}")

        # Checkout the CL
        print(f"Checking out {changespec_name}...")
        provider = get_vcs_provider(workspace_dir)
        resolved = provider.resolve_revision(
            changespec_name, project_basename, workspace_dir
        )
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            return (False, f"checkout failed: {checkout_err}")

        # Run sase_hg_reword --add-tag
        print(f"Adding tag {tag_name}={tag_value}...")
        tag_ok, tag_err = provider.reword_add_tag(tag_name, tag_value, workspace_dir)
        if tag_ok:
            from sase.ace.timestamps.recording import add_timestamp_entry_atomic

            add_timestamp_entry_atomic(
                changespec_file_path,
                changespec_name,
                "REWORD",
                f'tag "{tag_name}"',
            )

            # Sync BUG tag to ChangeSpec BUG field
            if tag_name.upper() == "BUG":
                from sase.status_state_machine.field_updates import (
                    update_changespec_bug_atomic,
                )

                try:
                    bug_id = (
                        tag_value.removeprefix("https://b/")
                        .removeprefix("http://b/")
                        .removeprefix("b/")
                    )
                    bug_url = f"http://b/{bug_id}"
                    update_changespec_bug_atomic(
                        changespec_file_path, changespec_name, bug_url
                    )
                    print("Synced BUG field to project file")
                except Exception as exc:
                    print(f"Warning: failed to sync BUG field: {exc}")

            return (True, f"Tag {tag_name}={tag_value} added to {changespec_name}")
        else:
            return (False, f"sase_hg_reword --add-tag failed: {tag_err}")

    finally:
        release_workspace(
            changespec_file_path, workspace_num, workflow_name, changespec_name
        )


def handle_reword_prepare(
    self: "WorkflowContext", changespec: ChangeSpec
) -> str | None:
    """Interactive part of reword: fetch description and open editor.

    Runs inside ``suspend()`` so the editor can take over the terminal.

    Args:
        self: The WorkflowContext instance (provides console for terminal output)
        changespec: Current ChangeSpec

    Returns:
        The edited description if changed, or None if cancelled/unchanged.
    """
    original = _fetch_cl_description(
        changespec.project_basename, changespec.name, self.console
    )
    if original is None:
        return None

    content_for_editor = _add_prettier_ignore_before_tags(original)
    edited = _open_editor_with_content(content_for_editor, self.console)
    if edited is None:
        self.console.print("[yellow]Reword cancelled.[/yellow]")
        return None

    # Strip prettier-ignore immediately after editor returns
    edited = _strip_prettier_ignore(edited)

    # Compare (ignore trailing newline differences)
    if original.rstrip("\n") == edited.rstrip("\n"):
        self.console.print("[yellow]Description unchanged, nothing to do.[/yellow]")
        return None

    return edited


def reword_execute_task(
    changespec_name: str,
    changespec_file_path: str,
    project_basename: str,
    edited_description: str,
) -> tuple[bool, str]:
    """Non-interactive: claim workspace, checkout CL, apply reword. Background task.

    Claims a workspace, checks out the CL, runs the reword with the edited
    description, syncs the description back to the project file, and releases
    the workspace in a finally block.

    Returns:
        Tuple of (success, message).
    """
    from sase.running_field import (
        claim_workspace,
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
        release_workspace,
    )

    workspace_num = get_first_available_axe_workspace(changespec_file_path)
    workflow_name = "reword"

    try:
        workspace_dir, workspace_suffix = get_workspace_directory_for_num(
            workspace_num, project_basename
        )
    except RuntimeError as e:
        return (False, f"Failed to get workspace directory: {e}")

    pid = os.getpid()
    if not claim_workspace(
        changespec_file_path, workspace_num, workflow_name, pid, changespec_name
    ):
        return (False, "Failed to claim workspace")

    try:
        if workspace_suffix:
            print(f"Using workspace: {workspace_suffix}")

        # Clean workspace before switching branches
        clean_success, clean_error = run_sase_hg_clean(
            workspace_dir, f"{changespec_name}-reword"
        )
        if not clean_success:
            print(f"Warning: sase_hg_clean failed: {clean_error}")

        # Checkout the CL
        print(f"Checking out {changespec_name}...")
        provider = get_vcs_provider(workspace_dir)
        resolved = provider.resolve_revision(
            changespec_name, project_basename, workspace_dir
        )
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            return (False, f"checkout failed: {checkout_err}")

        # Run reword with the edited description
        print("Rewording CL description...")
        escaped_desc = provider.prepare_description_for_reword(edited_description)
        reword_ok, reword_err = provider.reword(escaped_desc, workspace_dir)
        if not reword_ok:
            return (False, f"sase_hg_reword failed: {reword_err}")

        # Sync description to project file
        _sync_description_bg(workspace_dir, changespec_file_path, changespec_name)

        from sase.ace.timestamps.recording import add_timestamp_entry_atomic

        add_timestamp_entry_atomic(
            changespec_file_path,
            changespec_name,
            "REWORD",
            "description",
        )

        return (True, f"Reworded {changespec_name}")

    finally:
        release_workspace(
            changespec_file_path, workspace_num, workflow_name, changespec_name
        )
