"""Small support helpers for commit workflow dispatch and validation."""

from __future__ import annotations


def explicit_parent_resolves(parent_name: str) -> bool:
    """Return whether ``parent_name`` is a known Patch in this project.

    Resolution failures are treated as success so a transient error does not
    silently drop a legitimate parent reference.
    """
    try:
        from sase.workflows.commit.patch_queries import patch_exists_anywhere
        from sase.workflows.utils import get_project_from_workspace

        project_name = get_project_from_workspace()
        if not project_name:
            return True
        return patch_exists_anywhere(project_name, parent_name)
    except Exception:
        return True


def is_conflict_state(provider: object, cwd: str) -> bool:
    """Return whether the working tree appears to be in a merge-conflict state."""
    try:
        if provider.is_sync_in_progress(cwd):  # type: ignore[attr-defined]
            return True
    except NotImplementedError:
        pass
    except Exception:
        pass
    try:
        conflicted = provider.get_conflicted_files(cwd)  # type: ignore[attr-defined]
        if conflicted:
            return True
    except NotImplementedError:
        pass
    except Exception:
        pass
    return False


def classify_dispatch_failure(result: str | None) -> str:
    """Map a provider failure message to its telemetry reason."""
    text = (result or "").lower()
    if "no staged changes" in text or "nothing to commit" in text:
        return "no_staged_changes"
    if "push" in text:
        return "push_failed"
    if "conflict" in text or "rebase" in text or "merge" in text:
        return "sync_conflict"
    return "other"


def log_commit_failed(method: str, reason: str) -> None:
    """Best-effort logging for commit workflow failures."""
    try:
        from sase.logs.run_log import log_event

        log_event(event="commit_failed", method=method, reason=reason)
    except Exception:
        pass
