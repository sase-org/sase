"""Classification of failed ``git push`` output that lost a push race."""

_REMOTE_REJECTED = "[remote rejected]"
# Server-side spellings of a ref that moved between ref advertisement and the
# ref update. Hook declines, protected-branch refusals, and permission errors
# also render as ``[remote rejected]`` and must stay fatal.
_REMOTE_REF_RACE_MARKERS = (
    "cannot lock ref",
    "incorrect old value provided",
)


def is_retryable_push_race(stdout: str | None, stderr: str | None) -> bool:
    """Return whether a failed push lost a race and can succeed after integrating."""
    output = f"{stdout or ''}\n{stderr or ''}".lower()
    return (
        "non-fast-forward" in output
        or "fetch first" in output
        or "updates were rejected because the remote contains work" in output
        or ("[rejected]" in output and "failed to push some refs" in output)
        or (
            _REMOTE_REJECTED in output
            and any(marker in output for marker in _REMOTE_REF_RACE_MARKERS)
        )
    )


__all__ = ["is_retryable_push_race"]
