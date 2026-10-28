"""Workspace and diff management utilities."""

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.patch import strip_reverted_suffix
from sase.core.paths import make_safe_filename, sharded_path
from sase.core.time import generate_timestamp
from sase.vcs_provider import get_vcs_provider

if TYPE_CHECKING:
    from sase.workspace_provider.snapshot import SnapshotRecord


def _verified_snapshot_before_cleanup(
    workspace_dir: str,
    *,
    workspace_num: int,
    label: str,
    reason: str,
) -> "SnapshotRecord | None":
    """Capture a verified snapshot before a source-mutating cleanup.

    Returns the snapshot record, or ``None`` when the checkout is a proven
    no-work tree. Raises :class:`PreservationError` when preservation is
    incomplete; callers must not proceed to destructive Git operations.
    """
    from sase.workspace_provider.snapshot import snapshot_git_repo

    record = snapshot_git_repo(
        workspace_dir,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        label=label,
        reason=reason,
    )
    if record is not None:
        print(f"Verified preservation: {record.manifest_path}")
    return record


def save_diff(
    cl_name: str,
    target_dir: str | None = None,
    timestamp: str | None = None,
) -> str | None:
    """Save the current diff to a file.

    Args:
        cl_name: The Patch name (used in filename).
        target_dir: Optional directory to run diff in.
        timestamp: Optional timestamp for filename (YYmmdd_HHMMSS format).

    Returns:
        Path to the saved diff file (with ~ for home), or None if no changes.
    """
    cwd = target_dir or os.getcwd()
    provider = get_vcs_provider(cwd)

    # Run addremove to track new/deleted files before creating diff
    try:
        provider.add_remove(cwd)
    except Exception:
        pass  # Continue even if addremove fails

    # Run diff
    success, diff_content = provider.diff(cwd)
    if not success or not diff_content:
        return None

    # Generate filename: cl_name-timestamp.diff
    safe_name = make_safe_filename(strip_reverted_suffix(cl_name))
    if timestamp is None:
        timestamp = generate_timestamp()
    filename = f"{safe_name}-{timestamp}.diff"

    # Save the diff (sharded by YYYYMM).
    diff_path = sharded_path("diffs", filename)

    with open(diff_path, "w", encoding="utf-8") as f:
        f.write(diff_content)
        if not diff_content.endswith("\n"):
            f.write("\n")

    # Return path with ~ for home directory
    return diff_path.replace(str(Path.home()), "~")


def apply_diff_to_workspace(workspace_dir: str, diff_path: str) -> tuple[bool, str]:
    """Apply a saved diff to the workspace.

    Args:
        workspace_dir: The workspace directory to apply the diff in.
        diff_path: Path to the diff file (may use ~ for home).

    Returns:
        Tuple of (success, error_message). error_message is empty on success.
    """
    provider = get_vcs_provider(workspace_dir)
    success, error = provider.apply_patch(diff_path, workspace_dir)
    if not success:
        return False, error or "apply_patch failed"
    return True, ""


def apply_diffs_to_workspace(
    workspace_dir: str, diff_paths: list[str]
) -> tuple[bool, str]:
    """Apply multiple saved diffs to the workspace.

    Args:
        workspace_dir: The workspace directory to apply the diffs in.
        diff_paths: List of paths to diff files (may use ~ for home).

    Returns:
        Tuple of (success, error_message). error_message is empty on success.
    """
    if not diff_paths:
        return True, ""
    provider = get_vcs_provider(workspace_dir)
    success, error = provider.apply_patches(diff_paths, workspace_dir)
    if not success:
        return False, error or "apply_patches failed"
    return True, ""


def clean_workspace(workspace_dir: str, *, workspace_num: int = 1) -> bool:
    """Clean the workspace by reverting all uncommitted changes.

    Captures a verified snapshot before the first source-mutating reset so
    tracked, staged, and untracked bytes stay recoverable outside the
    checkout. A preservation failure refuses the clean.

    Args:
        workspace_dir: The workspace directory to clean.
        workspace_num: Owning workspace identity for rescue entry naming.

    Returns:
        True if successful, False otherwise.
    """
    try:
        _verified_snapshot_before_cleanup(
            workspace_dir,
            workspace_num=workspace_num,
            label="cleanup",
            reason="commit-utils clean_workspace before reset/clean",
        )
    except Exception as exc:
        print(f"verified preservation failed: {exc}", file=sys.stderr)
        return False
    try:
        provider = get_vcs_provider(workspace_dir)
        success, _ = provider.clean_workspace(workspace_dir)
        return success
    except Exception:
        return False


def run_sase_hg_clean(
    workspace_dir: str, diff_name: str, *, workspace_num: int = 1
) -> tuple[bool, str]:
    """Save changes and clean the workspace.

    This saves any uncommitted changes to a diff file before cleaning.
    Should be called BEFORE switching branches. A verified snapshot is
    captured before the stash so tracked, staged, and untracked bytes stay
    recoverable outside the checkout even when the stash cannot be created;
    ``--include-untracked`` stays in the normal stash path.

    Args:
        workspace_dir: The workspace directory to clean.
        diff_name: Name for the backup diff file (without .diff extension).
        workspace_num: Owning workspace identity for rescue entry naming.

    Returns:
        Tuple of (success, error_message).
    """
    try:
        _verified_snapshot_before_cleanup(
            workspace_dir,
            workspace_num=workspace_num,
            label="cleanup",
            reason=f"run_sase_hg_clean before stash_and_clean ({diff_name})",
        )
    except Exception as exc:
        return False, f"verified preservation failed: {exc}"
    try:
        provider = get_vcs_provider(workspace_dir)
        success, error = provider.stash_and_clean(diff_name, workspace_dir)
        if not success:
            return False, error or "stash_and_clean failed"
        return True, ""
    except Exception as e:
        return False, str(e)
