"""Git utility functions for diff generation."""

import subprocess


def git_diff_with_untracked(cwd: str, timeout: int = 10) -> str | None:
    """Generate a combined diff including both tracked changes and untracked files.

    Returns:
        Combined diff output, or None if no changes or an error occurred.
    """
    try:
        # 1. Get diff for tracked changes
        tracked = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        tracked_diff = tracked.stdout if tracked.returncode == 0 else ""

        # 2. Find untracked files
        ls_result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        untracked_diff = ""
        if ls_result.returncode == 0 and ls_result.stdout:
            files = [f for f in ls_result.stdout.split("\0") if f]
            for f in files[:100]:
                # git diff --no-index exits 1 when files differ (expected)
                result = subprocess.run(
                    ["git", "diff", "--no-index", "/dev/null", f],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                if result.stdout:
                    untracked_diff += result.stdout

        combined = tracked_diff + untracked_diff
        return combined if combined.strip() else None
    except (subprocess.TimeoutExpired, Exception):
        return None


def git_committed_diff(cwd: str, timeout: int = 10) -> str | None:
    """Get the diff from the most recent commit (for agents that already committed).

    Returns:
        Diff output from the last commit, or None if unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1..HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        return None
    except (subprocess.TimeoutExpired, Exception):
        return None
