"""sase.core facade for deterministic Git query parsers.

This is the Rust-bindable seam for the small parsing/normalization
helpers shared by :class:`sase.vcs_provider.plugins._git_query_ops.GitQueryOpsMixin`.
Each helper is a *pure function* over strings produced by ``git``; the
host stays responsible for running the command, handling timeouts and
process errors, touching the filesystem, and performing every mutation.

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

Phase 8E direct-wires these helpers to ``sase_core_rs`` without going
through :func:`sase.core.backend.dispatch`. The backend-selection env
vars no longer affect them; the strict loader from
:mod:`sase.core.rust` raises :class:`ImportError` when the wheel is
missing and :class:`AttributeError` when the wheel is too old to expose
the requested binding.

The ``*_python`` helpers below remain as host-logic / golden-contract
references — every parity test against the Rust output uses them as the
byte-for-byte expectation, and they are the only practical way to keep
Rust regressions visible in pure-Python checkouts during development.
They are not backend fallbacks.
"""

from __future__ import annotations

import os

from sase.core.git_query_wire import (
    GitNameStatusEntryWire,
    git_name_status_entry_from_dict,
)
from sase.core.rust import require_rust_binding


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
def parse_git_name_status_z_python(stdout: str) -> list[tuple[str, str]]:
    """Public Python golden-contract implementation of :func:`parse_git_name_status_z`.

    Flattens the wire records produced by
    :func:`_parse_git_name_status_z_python` into the legacy
    ``list[tuple[str, str]]`` shape that ``vcs_diff_name_status``
    consumes. Retained as a host-logic golden reference so parity tests
    against the Rust binding remain meaningful.
    """
    entries = _parse_git_name_status_z_python(stdout)
    return [(entry.status, entry.path) for entry in entries]


def parse_git_name_status_z(stdout: str) -> list[tuple[str, str]]:
    """Parse the NUL-delimited output of ``git diff --name-status -z``.

    Returns a list of ``(status, path)`` tuples that matches the legacy
    public shape used by ``vcs_diff_name_status``. Rename/copy entries
    carry their two paths joined by a literal tab character
    (``"<old>\\t<new>"``) so callers can split them apart without losing
    information.

    Phase 8E: calls ``sase_core_rs.parse_git_name_status_z`` via
    :func:`require_rust_binding` and flattens the dict output into the
    legacy tuple shape. A missing wheel raises :class:`ImportError`; a
    stale wheel without the binding raises :class:`AttributeError`.
    """
    binding = require_rust_binding("parse_git_name_status_z")
    raw: list[dict[str, str]] = binding(stdout)
    return [
        (entry.status, entry.path)
        for entry in (git_name_status_entry_from_dict(item) for item in raw)
    ]


# pyvision: tests/test_core_git_query.py
def parse_git_branch_name_python(stdout: str) -> str | None:
    """Pure-Python golden-contract implementation of :func:`parse_git_branch_name`."""
    name = stdout.strip()
    if not name or name == "HEAD":
        return None
    return name


def parse_git_branch_name(stdout: str) -> str | None:
    """Normalize ``git rev-parse --abbrev-ref HEAD`` stdout into a branch name.

    Returns ``None`` when the stripped stdout is empty or equals
    ``"HEAD"`` (detached-HEAD state in the Git provider's contract).
    Otherwise returns the trimmed branch name verbatim. Calls
    ``sase_core_rs.parse_git_branch_name`` directly.
    """
    binding = require_rust_binding("parse_git_branch_name")
    return binding(stdout)  # type: ignore[no-any-return]


# pyvision: tests/test_core_git_query.py
def derive_git_workspace_name_python(
    remote_url: str | None, root_path: str | None
) -> str | None:
    """Pure-Python golden-contract implementation of :func:`derive_git_workspace_name`."""
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


def derive_git_workspace_name(
    remote_url: str | None, root_path: str | None
) -> str | None:
    """Derive a workspace name from a remote URL or repository root path.

    The Git provider prefers ``git config --get remote.origin.url`` and
    falls back to ``git rev-parse --show-toplevel`` when the remote is
    unset. Calls ``sase_core_rs.derive_git_workspace_name`` directly.
    """
    binding = require_rust_binding("derive_git_workspace_name")
    return binding(remote_url, root_path)  # type: ignore[no-any-return]


# pyvision: tests/test_core_git_query.py
def parse_git_conflicted_files_python(stdout: str) -> list[str]:
    """Pure-Python golden-contract implementation of :func:`parse_git_conflicted_files`."""
    return [line for line in stdout.split("\n") if line.strip()]


def parse_git_conflicted_files(stdout: str) -> list[str]:
    """Split ``git diff --name-only --diff-filter=U`` stdout into paths.

    The Git provider expects an empty list when ``stdout`` is empty (or
    contains only blank lines) so callers do not have to special-case
    "no conflicts". Whitespace-only lines are dropped; non-empty paths
    are preserved verbatim (no rstrip beyond the line split). Calls
    ``sase_core_rs.parse_git_conflicted_files`` directly.
    """
    binding = require_rust_binding("parse_git_conflicted_files")
    return binding(stdout)  # type: ignore[no-any-return]


# pyvision: tests/test_core_git_query.py
def parse_git_local_changes_python(stdout: str) -> str | None:
    """Pure-Python golden-contract implementation of :func:`parse_git_local_changes`."""
    text = stdout.strip()
    return text if text else None


def parse_git_local_changes(stdout: str) -> str | None:
    """Normalize ``git status --porcelain`` stdout into a clean/dirty signal.

    Returns ``None`` when the stripped stdout is empty (clean tree); the
    original stripped text otherwise so the Git provider can echo it
    back as a dirty-tree summary. Mirrors the behavior of
    ``vcs_has_local_changes`` on a successful command run. Calls
    ``sase_core_rs.parse_git_local_changes`` directly.
    """
    binding = require_rust_binding("parse_git_local_changes")
    return binding(stdout)  # type: ignore[no-any-return]


__all__ = [
    "derive_git_workspace_name",
    "derive_git_workspace_name_python",
    "parse_git_branch_name",
    "parse_git_branch_name_python",
    "parse_git_conflicted_files",
    "parse_git_conflicted_files_python",
    "parse_git_local_changes",
    "parse_git_local_changes_python",
    "parse_git_name_status_z",
    "parse_git_name_status_z_python",
]
