"""Change tokens and invalidation for ACE memory history.

One section of :class:`sase.ace.tui.memory_history.AceMemoryHistory`:
the stat-only change tokens (no git subprocess, no core query), the
quiet-time drift probe, and explicit invalidation. Import from
:mod:`sase.ace.tui.memory_history`, not from here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui._memory_history_base import HistoryQueryBase


def _stat_token(path: Path) -> tuple[int, int] | None:
    """Return ``(mtime_ns, size)`` for *path*, or ``None`` when unreadable."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _head_ref_name(git_dir: Path) -> str | None:
    """Return the ref file ``HEAD`` names (``refs/heads/x``), if any."""
    try:
        text = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if text.startswith("ref:"):
        ref = text[len("ref:") :].strip()
        if ref and ".." not in ref and not ref.startswith("/"):
            return ref
    return None


class TokenQueries(HistoryQueryBase):
    """Stat-only change tokens, drift probes, and invalidation."""

    def _git_dir_for_scope(self, scope: Any) -> Path | None:
        """Return the scope repo's git dir, resolving ``.git`` files once."""
        scope_key = str(getattr(scope, "scope_key", "") or "")
        with self._lock:
            if scope_key in self._git_dirs:
                return self._git_dirs[scope_key]
        repo_root = Path(str(getattr(scope, "repo_root", "") or ""))
        git_dir: Path | None = None
        try:
            dot_git = repo_root / ".git"
            if dot_git.is_dir():
                git_dir = dot_git
            elif dot_git.is_file():
                text = dot_git.read_text(encoding="utf-8").strip()
                if text.startswith("gitdir:"):
                    target = text[len("gitdir:") :].strip()
                    candidate = Path(target)
                    git_dir = (
                        candidate
                        if candidate.is_absolute()
                        else (repo_root / candidate)
                    )
        except OSError:
            git_dir = None
        with self._lock:
            self._git_dirs[scope_key] = git_dir
        return git_dir

    def change_token(
        self, scope: Any, subject: str | Path | None = None
    ) -> tuple[Any, ...]:
        """Return a stat-only change token for a scope (plus subject file).

        Covers the scope repo's HEAD file, the ref it names,
        ``packed-refs``, and the index (mtime_ns and size), plus the
        selected subject's worktree file when given. Pure stat calls:
        no git subprocess, no core query.
        """
        parts: list[Any] = []
        git_dir = self._git_dir_for_scope(scope)
        if git_dir is not None:
            parts.append(_stat_token(git_dir / "HEAD"))
            ref = _head_ref_name(git_dir)
            parts.append(_stat_token(git_dir / ref) if ref else None)
            parts.append(_stat_token(git_dir / "packed-refs"))
            parts.append(_stat_token(git_dir / "index"))
        else:
            parts.append(None)
        if subject is not None:
            candidate = Path(str(subject))
            if not candidate.is_absolute():
                candidate = Path(str(getattr(scope, "repo_root", "") or "")) / candidate
            parts.append(_stat_token(candidate))
        return tuple(parts)

    @staticmethod
    def _subject_file(scope: Any, selector: str) -> Path | None:
        """Return the subject's worktree file when *selector* is a path."""
        try:
            candidate = Path(selector)
            if not candidate.is_absolute():
                candidate = Path(str(getattr(scope, "repo_root", "") or "")) / candidate
            return candidate if candidate.is_file() else None
        except OSError:
            return None

    def poll_changed(self, scope: Any, selector: str) -> bool:
        """Return whether the scope/subject drifted since the last poll.

        The token covers the scope git state plus the selected
        subject's worktree file whenever the selector names one. The
        first poll establishes the baseline and returns False, so the
        quiet-time probe never fires spuriously on startup.
        """
        scope_key = str(getattr(scope, "scope_key", "") or "")
        key = (scope_key, str(selector))
        token = self.change_token(scope, self._subject_file(scope, str(selector)))
        with self._lock:
            seen = self._seen_tokens.get(key)
            self._seen_tokens[key] = token
            if seen is None:
                return False
            return seen != token

    def invalidate_subject(self, scope_key: str, selector: str) -> None:
        """Drop a subject's memoized entries and refetch on next use."""
        with self._lock:
            for key in [
                key for key in self._timeline_memo if key[:2] == (scope_key, selector)
            ]:
                del self._timeline_memo[key]
            for blob_key in [
                key for key in self._blob_memo if key[:2] == (scope_key, selector)
            ]:
                del self._blob_memo[blob_key]
            self._seen_tokens.pop((scope_key, selector), None)
            for memo_key in [
                key for key in self._known_blobs if key[:2] == (scope_key, selector)
            ]:
                del self._known_blobs[memo_key]
            self._subjects_memo.pop(scope_key, None)
            for feed_key in [key for key in self._feed_memo if scope_key in key]:
                del self._feed_memo[feed_key]

    def invalidate_scope(self, scope_key: str) -> None:
        """Drop every memoized entry for a scope key."""
        with self._lock:
            for key in [key for key in self._timeline_memo if key[0] == scope_key]:
                del self._timeline_memo[key]
            for blob_key in [key for key in self._blob_memo if key[0] == scope_key]:
                del self._blob_memo[blob_key]
            for memo_key in [key for key in self._known_blobs if key[0] == scope_key]:
                del self._known_blobs[memo_key]
            self._seen_tokens = {
                key: token
                for key, token in self._seen_tokens.items()
                if key[0] != scope_key
            }
            self._subjects_memo.pop(scope_key, None)
            for feed_key in [key for key in self._feed_memo if scope_key in key]:
                del self._feed_memo[feed_key]
