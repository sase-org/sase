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

Phase 5D classifies all five helpers as **shipped** Rust operations:
when ``sase_core_rs`` is importable and exposes the matching binding,
:func:`sase.core.backend.dispatch` registers it as ``rust_impl`` and
``SASE_CORE_BACKEND=rust`` routes through Rust. A missing binding under
Rust mode raises :class:`sase.core.backend.RustBackendUnavailableError`
rather than silently falling back. ``SASE_CORE_DUAL_RUN=1`` runs both
implementations on every dispatched call and logs a comparison record
to ``~/.sase/perf/core_dual_run.jsonl``.
"""

from __future__ import annotations

import os

from sase.core.backend import dispatch, load_rust_extension
from sase.core.git_query_wire import (
    GitNameStatusEntryWire,
    git_name_status_entry_from_dict,
)


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
    """Public Python implementation of :func:`parse_git_name_status_z`.

    Flattens the wire records produced by
    :func:`_parse_git_name_status_z_python` into the legacy
    ``list[tuple[str, str]]`` shape that ``vcs_diff_name_status``
    consumes. Exposed at module scope (rather than as a closure inside
    :func:`parse_git_name_status_z`) so the dual-run comparator and
    parity tests can call it directly without going through the
    backend dispatcher.
    """
    entries = _parse_git_name_status_z_python(stdout)
    return [(entry.status, entry.path) for entry in entries]


def _rust_parse_git_name_status_z_impl(stdout: str) -> list[tuple[str, str]]:
    """Adapter from ``sase_core_rs.parse_git_name_status_z`` to flat tuples.

    The PyO3 binding returns ``list[dict]`` (``{"status": ..., "path": ...}``).
    The adapter rehydrates each dict via
    :func:`git_name_status_entry_from_dict` and flattens to
    ``list[tuple[str, str]]`` so the public facade output is
    backend-independent.
    """
    rust_module = load_rust_extension()
    if rust_module is None:
        raise RuntimeError(
            "sase_core_rs is not importable; the Rust backend was registered "
            "but the extension module disappeared at call time."
        )
    raw: list[dict[str, str]] = rust_module.parse_git_name_status_z(stdout)  # type: ignore[attr-defined]
    return [
        (entry.status, entry.path)
        for entry in (git_name_status_entry_from_dict(item) for item in raw)
    ]


def parse_git_name_status_z(stdout: str) -> list[tuple[str, str]]:
    """Parse the NUL-delimited output of ``git diff --name-status -z``.

    Returns a list of ``(status, path)`` tuples that matches the legacy
    public shape used by ``vcs_diff_name_status``. Rename/copy entries
    carry their two paths joined by a literal tab character (``"<old>\\t<new>"``)
    so callers can split them apart without losing information.

    Routes through :func:`sase.core.backend.dispatch`: under
    ``SASE_CORE_BACKEND=rust`` (with the Rust extension installed) the
    call is served by ``sase_core_rs.parse_git_name_status_z`` and its
    dict output is flattened into the legacy tuple shape inside
    :func:`_rust_parse_git_name_status_z_impl`. Under
    ``SASE_CORE_DUAL_RUN=1`` both implementations run and the results
    are compared after flattening, so the comparison key is the public
    tuple shape the call site sees.
    """
    rust_module = load_rust_extension()
    rust_impl = (
        _rust_parse_git_name_status_z_impl
        if rust_module is not None and hasattr(rust_module, "parse_git_name_status_z")
        else None
    )
    return dispatch(
        operation="parse_git_name_status_z",
        python_impl=parse_git_name_status_z_python,
        rust_impl=rust_impl,
        args=(stdout,),
    )


# pyvision: tests/test_core_git_query.py
def parse_git_branch_name_python(stdout: str) -> str | None:
    """Pure-Python implementation of :func:`parse_git_branch_name`."""
    name = stdout.strip()
    if not name or name == "HEAD":
        return None
    return name


def _rust_parse_git_branch_name_impl(stdout: str) -> str | None:
    """Adapter from ``sase_core_rs.parse_git_branch_name`` to ``str | None``."""
    rust_module = load_rust_extension()
    if rust_module is None:
        raise RuntimeError(
            "sase_core_rs is not importable; the Rust backend was registered "
            "but the extension module disappeared at call time."
        )
    return rust_module.parse_git_branch_name(stdout)  # type: ignore[attr-defined,no-any-return]


def parse_git_branch_name(stdout: str) -> str | None:
    """Normalize ``git rev-parse --abbrev-ref HEAD`` stdout into a branch name.

    Returns ``None`` when the stripped stdout is empty or equals
    ``"HEAD"`` (detached-HEAD state in the Git provider's contract).
    Otherwise returns the trimmed branch name verbatim. Routes through
    the backend dispatcher; see :func:`parse_git_name_status_z` for the
    Rust mode / dual-run contract.
    """
    rust_module = load_rust_extension()
    rust_impl = (
        _rust_parse_git_branch_name_impl
        if rust_module is not None and hasattr(rust_module, "parse_git_branch_name")
        else None
    )
    return dispatch(
        operation="parse_git_branch_name",
        python_impl=parse_git_branch_name_python,
        rust_impl=rust_impl,
        args=(stdout,),
    )


# pyvision: tests/test_core_git_query.py
def derive_git_workspace_name_python(
    remote_url: str | None, root_path: str | None
) -> str | None:
    """Pure-Python implementation of :func:`derive_git_workspace_name`."""
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


def _rust_derive_git_workspace_name_impl(
    remote_url: str | None, root_path: str | None
) -> str | None:
    """Adapter from ``sase_core_rs.derive_git_workspace_name``."""
    rust_module = load_rust_extension()
    if rust_module is None:
        raise RuntimeError(
            "sase_core_rs is not importable; the Rust backend was registered "
            "but the extension module disappeared at call time."
        )
    return rust_module.derive_git_workspace_name(remote_url, root_path)  # type: ignore[attr-defined,no-any-return]


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

    Routes through the backend dispatcher; see
    :func:`parse_git_name_status_z` for the Rust mode / dual-run
    contract.
    """
    rust_module = load_rust_extension()
    rust_impl = (
        _rust_derive_git_workspace_name_impl
        if rust_module is not None and hasattr(rust_module, "derive_git_workspace_name")
        else None
    )
    return dispatch(
        operation="derive_git_workspace_name",
        python_impl=derive_git_workspace_name_python,
        rust_impl=rust_impl,
        args=(remote_url, root_path),
    )


# pyvision: tests/test_core_git_query.py
def parse_git_conflicted_files_python(stdout: str) -> list[str]:
    """Pure-Python implementation of :func:`parse_git_conflicted_files`."""
    return [line for line in stdout.split("\n") if line.strip()]


def _rust_parse_git_conflicted_files_impl(stdout: str) -> list[str]:
    """Adapter from ``sase_core_rs.parse_git_conflicted_files``."""
    rust_module = load_rust_extension()
    if rust_module is None:
        raise RuntimeError(
            "sase_core_rs is not importable; the Rust backend was registered "
            "but the extension module disappeared at call time."
        )
    return rust_module.parse_git_conflicted_files(stdout)  # type: ignore[attr-defined,no-any-return]


def parse_git_conflicted_files(stdout: str) -> list[str]:
    """Split ``git diff --name-only --diff-filter=U`` stdout into paths.

    The Git provider expects an empty list when ``stdout`` is empty (or
    contains only blank lines) so callers do not have to special-case
    "no conflicts". Whitespace-only lines are dropped; non-empty paths
    are preserved verbatim (no rstrip beyond the line split). Routes
    through the backend dispatcher; see :func:`parse_git_name_status_z`
    for the Rust mode / dual-run contract.
    """
    rust_module = load_rust_extension()
    rust_impl = (
        _rust_parse_git_conflicted_files_impl
        if rust_module is not None
        and hasattr(rust_module, "parse_git_conflicted_files")
        else None
    )
    return dispatch(
        operation="parse_git_conflicted_files",
        python_impl=parse_git_conflicted_files_python,
        rust_impl=rust_impl,
        args=(stdout,),
    )


# pyvision: tests/test_core_git_query.py
def parse_git_local_changes_python(stdout: str) -> str | None:
    """Pure-Python implementation of :func:`parse_git_local_changes`."""
    text = stdout.strip()
    return text if text else None


def _rust_parse_git_local_changes_impl(stdout: str) -> str | None:
    """Adapter from ``sase_core_rs.parse_git_local_changes``."""
    rust_module = load_rust_extension()
    if rust_module is None:
        raise RuntimeError(
            "sase_core_rs is not importable; the Rust backend was registered "
            "but the extension module disappeared at call time."
        )
    return rust_module.parse_git_local_changes(stdout)  # type: ignore[attr-defined,no-any-return]


def parse_git_local_changes(stdout: str) -> str | None:
    """Normalize ``git status --porcelain`` stdout into a clean/dirty signal.

    Returns ``None`` when the stripped stdout is empty (clean tree); the
    original stripped text otherwise so the Git provider can echo it
    back as a dirty-tree summary. Mirrors the behavior of
    ``vcs_has_local_changes`` on a successful command run. Routes
    through the backend dispatcher; see :func:`parse_git_name_status_z`
    for the Rust mode / dual-run contract.
    """
    rust_module = load_rust_extension()
    rust_impl = (
        _rust_parse_git_local_changes_impl
        if rust_module is not None and hasattr(rust_module, "parse_git_local_changes")
        else None
    )
    return dispatch(
        operation="parse_git_local_changes",
        python_impl=parse_git_local_changes_python,
        rust_impl=rust_impl,
        args=(stdout,),
    )


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
