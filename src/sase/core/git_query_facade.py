"""sase.core facade for deterministic Git query parsers.

This is the Rust-bindable seam for the small parsing/normalization
helpers shared by :class:`sase.vcs_provider.plugins._git_query_ops.GitQueryOpsMixin`
(Phase 5 of ``research/202604/rust_backend_migration.md`` and
``plans/202604/rust_backend_phase5_git_query_ops.md``). Each helper is a
*pure function* over strings produced by ``git``; the host stays
responsible for running the command, handling timeouts and process
errors, touching the filesystem, and performing every mutation.

The five Phase 5 helpers are:

- :func:`parse_git_name_status_z` — parse ``git diff --name-status -z``
  output into ``list[tuple[str, str]]``.
- :func:`parse_git_branch_name` — normalize ``git rev-parse --abbrev-ref
  HEAD`` stdout into a branch name (``None`` for detached HEAD or empty).
- :func:`derive_git_workspace_name` — derive a workspace name from a
  remote URL (preferred) or repository root path.
- :func:`parse_git_conflicted_files` — split ``git diff --name-only
  --diff-filter=U`` stdout into a list of paths.
- :func:`parse_git_local_changes` — normalize ``git status --porcelain``
  stdout into ``str | None`` (clean → ``None``).

Phase 5B keeps every helper on the Python implementation. No
``sase_core_rs`` import happens here yet — the facade is intentionally
shaped so Phase 5C can register Rust ``rust_impl`` callbacks one at a
time without changing call sites. Phase 5D will route the helpers
through :func:`sase.core.backend.dispatch` once the bindings exist.
"""

from __future__ import annotations

import os

from sase.core.git_query_wire import GitNameStatusEntryWire


def _parse_git_name_status_z_python(stdout: str) -> list[GitNameStatusEntryWire]:
    """Pure-Python implementation of :func:`parse_git_name_status_z`.

    The output of ``git diff --name-status -z`` is a stream of
    NUL-separated fields: a status token (e.g. ``A``, ``M``, ``D``,
    ``R100``, ``C75``, ``T``, ``U``) followed by one or two paths.
    Rename/copy entries (``R`` / ``C``) are followed by *two* paths
    (old, new); all other statuses are followed by exactly one. Trailing
    NUL terminators are tolerated. Truncated streams (a status with no
    following path, or a rename with only one path) are silently dropped
    so a single malformed entry does not poison the whole list.
    """
    if not stdout:
        return []
    parts = stdout.split("\0")
    if parts and parts[-1] == "":
        parts.pop()

    result: list[GitNameStatusEntryWire] = []
    i = 0
    while i < len(parts):
        status = parts[i]
        i += 1
        if not status:
            continue
        first_letter = status[0]
        if first_letter in ("R", "C") and i + 1 < len(parts):
            old_path = parts[i]
            new_path = parts[i + 1]
            i += 2
            result.append(
                GitNameStatusEntryWire(status=status, path=f"{old_path}\t{new_path}")
            )
        elif i < len(parts):
            path = parts[i]
            i += 1
            result.append(GitNameStatusEntryWire(status=status, path=path))
    return result


# pyvision: tests/test_core_git_query.py
def parse_git_name_status_z(stdout: str) -> list[tuple[str, str]]:
    """Parse the NUL-delimited output of ``git diff --name-status -z``.

    Returns a list of ``(status, path)`` tuples that matches the legacy
    public shape used by ``vcs_diff_name_status``. Rename/copy entries
    carry their two paths joined by a literal tab character (``"<old>\\t<new>"``)
    so callers can split them apart without losing information.

    Phase 5B keeps the implementation in Python. The wire records
    produced internally by :func:`_parse_git_name_status_z_python` are
    flattened back into tuples here so the public API stays
    tuple-compatible with current call sites.
    """
    entries = _parse_git_name_status_z_python(stdout)
    return [(entry.status, entry.path) for entry in entries]


# pyvision: tests/test_core_git_query.py
def parse_git_branch_name(stdout: str) -> str | None:
    """Normalize ``git rev-parse --abbrev-ref HEAD`` stdout into a branch name.

    Returns ``None`` when the stripped stdout is empty or equals
    ``"HEAD"`` (detached-HEAD state in the Git provider's contract).
    Otherwise returns the trimmed branch name verbatim.
    """
    name = stdout.strip()
    if not name or name == "HEAD":
        return None
    return name


# pyvision: tests/test_core_git_query.py
def derive_git_workspace_name(
    remote_url: str | None, root_path: str | None
) -> str | None:
    """Derive a workspace name from a remote URL or repository root path.

    The Git provider prefers ``git config --get remote.origin.url`` and
    falls back to ``git rev-parse --show-toplevel`` when the remote is
    unset. This helper mirrors that priority:

    - When ``remote_url`` is non-empty after stripping, take its basename
      (the segment after the last ``/``) and drop a single trailing
      ``.git`` suffix if present. SSH-style remotes (``git@host:owner/repo.git``)
      and path-like remotes (``/srv/git/repo``) are handled the same way
      because the basename split is purely on ``/``.
    - Otherwise, when ``root_path`` is non-empty after stripping, take
      its basename via :func:`os.path.basename`.
    - Returning ``None`` indicates neither input produced a non-empty
      name; the Git provider surfaces this as a soft "could not
      determine workspace name" failure.
    """
    if remote_url is not None:
        url = remote_url.strip()
        if url:
            # Use forward-slash splitting so SSH-style ``git@host:owner/repo.git``
            # and URLs with ``://`` schemes both fall back to the trailing
            # path segment that ``os.path.basename`` would produce.
            name = url.rsplit("/", 1)[-1]
            if name.endswith(".git"):
                name = name[:-4]
            if name:
                return name
            return None
    if root_path is not None:
        root = root_path.strip()
        if root:
            name = os.path.basename(root)
            if name:
                return name
    return None


# pyvision: tests/test_core_git_query.py
def parse_git_conflicted_files(stdout: str) -> list[str]:
    """Split ``git diff --name-only --diff-filter=U`` stdout into paths.

    The Git provider expects an empty list when ``stdout`` is empty (or
    contains only blank lines) so callers do not have to special-case
    "no conflicts". Whitespace-only lines are dropped; non-empty paths
    are preserved verbatim (no rstrip beyond the line split).
    """
    return [line for line in stdout.split("\n") if line.strip()]


# pyvision: tests/test_core_git_query.py
def parse_git_local_changes(stdout: str) -> str | None:
    """Normalize ``git status --porcelain`` stdout into a clean/dirty signal.

    Returns ``None`` when the stripped stdout is empty (clean tree); the
    original stripped text otherwise so the Git provider can echo it
    back as a dirty-tree summary. Mirrors the behavior of
    ``vcs_has_local_changes`` on a successful command run.
    """
    text = stdout.strip()
    return text if text else None


__all__ = [
    "derive_git_workspace_name",
    "parse_git_branch_name",
    "parse_git_conflicted_files",
    "parse_git_local_changes",
    "parse_git_name_status_z",
]
