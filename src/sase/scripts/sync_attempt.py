"""Sync attempt step: call sync_workspace() and detect conflicts."""

from sase.vcs_provider._registry import get_vcs_provider


def main(*, cwd: str) -> None:
    """Attempt to sync the workspace and report the outcome.

    Always exits 0 — control flow is driven by output fields, not exit codes.

    Prints key=value output:
    - ``success``: whether sync completed without issues
    - ``has_conflicts``: whether merge conflicts were detected
    - ``error``: error message (empty string if none)
    - ``conflicted_files``: newline-separated list of conflicted file paths
    """
    provider = get_vcs_provider(cwd)
    success, error = provider.sync_workspace(cwd)

    if success:
        print("success=true")
        print("has_conflicts=false")
        print("error=")
        print("conflicted_files=")
        return

    # Sync failed — check if it's due to conflicts or another error
    if provider.is_sync_in_progress(cwd):
        conflicted = provider.get_conflicted_files(cwd)
        files_str = "\n".join(conflicted)
        print("success=false")
        print("has_conflicts=true")
        print(f"error={error or ''}")
        print(f"conflicted_files={files_str}")
    else:
        print("success=false")
        print("has_conflicts=false")
        print(f"error={error or ''}")
        print("conflicted_files=")
