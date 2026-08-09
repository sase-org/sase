"""Shared utility functions for workflow modules."""

import os
import subprocess

from sase.ace.patch import ChangeSpec, parse_project_file
from sase.core.paths import sase_projects_dir
from sase.vcs_provider import get_vcs_provider


def get_project_file_path(project: str) -> str:
    """Get the path to the project file for a given project.

    Prefers the canonical ``.sase`` file; falls back to a legacy ``.gp`` file
    when one already exists on disk. If neither exists, the returned path
    uses the canonical ``.sase`` extension so callers have a stable
    destination for writes.
    """
    from sase.ace.patch.project_spec_path import preferred_project_spec_path

    project_dir = str(sase_projects_dir() / project)
    return preferred_project_spec_path(project_dir, project)


def get_cl_name_from_branch() -> str | None:
    """Get the current ChangeSpec name from branch_name command.

    Returns:
        The ChangeSpec name, or None if not on a branch.
    """
    cwd = os.getcwd()
    provider = get_vcs_provider(cwd)
    success, branch_name = provider.get_branch_name(cwd)
    if not success:
        return None
    return branch_name if branch_name else None


def get_project_from_workspace() -> str | None:
    """Get the canonical project name for the current workspace.

    The provider-derived workspace name is a repo name (e.g. ``sase``),
    which may be another project's PROJECT_NAME or alias rather than a
    project directory key (e.g. ``gh_sase-org__sase``). Resolve it through
    the project alias map so callers never mint or write to a phantom
    project keyed by a display name.

    Returns:
        The canonical project name, or None if detection fails.
    """
    cwd = os.getcwd()
    provider = get_vcs_provider(cwd)
    success, ws_name = provider.get_workspace_name(cwd)
    if not success or not ws_name:
        return None
    try:
        from sase.project_aliases import resolve_project_alias_ref

        return resolve_project_alias_ref(ws_name)
    except Exception:
        # Canonicalization is best-effort; fall back to the raw name so
        # commit flows keep working even if project records are unreadable.
        return ws_name


def _get_changed_test_targets(verbose: bool = False) -> str | None:
    """Get test targets from changed files in the current branch.

    Calls the `changed_test_targets` script to get Blaze test targets
    for files that have changed in the current branch.

    Args:
        verbose: If True, print diagnostic messages when command fails.

    Returns:
        Space-separated test targets string, or None if no targets found
        or the command fails.
    """
    from sase.output import print_status

    try:
        result = subprocess.run(
            ["changed_test_targets"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            targets = result.stdout.strip()
            if targets:
                return targets
            if verbose:
                print_status("changed_test_targets returned empty output.", "info")
        elif verbose:
            stderr_preview = result.stderr.strip()[:100] if result.stderr else ""
            print_status(
                f"changed_test_targets failed (exit {result.returncode})"
                + (f": {stderr_preview}" if stderr_preview else ""),
                "warning",
            )
    except FileNotFoundError:
        if verbose:
            print_status("changed_test_targets command not found.", "warning")
    except Exception as e:
        if verbose:
            print_status(f"changed_test_targets error: {e}", "warning")
    return None


def get_initial_hooks_for_changespec(verbose: bool = True) -> list[str]:
    """Get all hooks to include in a new ChangeSpec.

    Returns required hooks (configurable via sase.yml, defaults to
    sase_hg_presubmit/sase_hg_lint for hg repos, empty for git repos)
    plus any test target hooks from changed_test_targets.

    Args:
        verbose: If True, print diagnostic messages for test target detection.

    Returns:
        List of hook command strings in order (required hooks first, then test targets).
    """
    from sase.ace.hooks.defaults import get_required_patch_hooks
    from sase.ace.hooks.test_targets import TEST_TARGET_HOOK_PREFIX

    hooks: list[str] = list(get_required_patch_hooks())

    test_targets = _get_changed_test_targets(verbose=verbose)
    if test_targets:
        for target in test_targets.split():
            hooks.append(f"{TEST_TARGET_HOOK_PREFIX}{target}")

    return hooks


def get_changespec_from_file(project_file: str, cl_name: str) -> ChangeSpec | None:
    """Get a ChangeSpec from a project file by name.

    Args:
        project_file: Path to the project file.
        cl_name: The ChangeSpec name to look for.

    Returns:
        The ChangeSpec if found, None otherwise.
    """
    changespecs = parse_project_file(project_file)
    for cs in changespecs:
        if cs.name == cl_name:
            return cs
    return None


get_patch_from_file = get_changespec_from_file


def add_test_hooks_if_available(
    project_file: str,
    cl_name: str,
    workspace_dir: str | None = None,
    verbose: bool = True,
) -> bool:
    """Add test target hooks from changed_test_targets if available.

    This centralizes the logic for adding test target hooks, which is used by:
    - commit_workflow
    - amend_workflow
    - accept_workflow
    - _auto_accept_proposal (completer)

    Args:
        project_file: Path to the project file.
        cl_name: The ChangeSpec name.
        workspace_dir: Optional workspace directory to run the command in.
                       If provided, changes to this directory before running
                       changed_test_targets, then restores the original directory.
        verbose: If True, print status messages.

    Returns:
        True if test hooks were added or none were needed, False on error.
    """
    from sase.ace.hooks import add_test_target_hooks_to_changespec
    from sase.output import print_status

    # Run changed_test_targets in the specified directory if provided
    original_dir = None
    if workspace_dir:
        original_dir = os.getcwd()
        os.chdir(workspace_dir)

    try:
        test_targets = _get_changed_test_targets(verbose=verbose)
    finally:
        if original_dir:
            os.chdir(original_dir)

    if not test_targets:
        return True  # No targets to add, not an error

    if verbose:
        print_status("Checking for new test target hooks...", "progress")

    target_list = test_targets.split()

    # Don't pass existing_hooks - let add_test_target_hooks_to_changespec read
    # fresh state inside the lock to avoid race conditions with sase axe
    if add_test_target_hooks_to_changespec(project_file, cl_name, target_list):
        if verbose:
            print_status(f"Added {len(target_list)} test target hook(s).", "success")
        return True
    else:
        if verbose:
            print_status("Failed to add test target hooks.", "warning")
        return False
