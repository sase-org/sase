"""Shared views and store helpers for the Admin Center Tools pane.

This module is private; the names it defines are public so the
``tool_runs_pane_*`` sibling modules can share them without importing
``_``-prefixed names across modules.
"""

from __future__ import annotations

VIEWS: tuple[str, ...] = ("runs", "failures", "catalog")


def store_token() -> tuple[object, ...]:
    """Stat the ToolRun store files; a quiet tick opens nothing else."""

    try:
        from sase.core.tool_run import tool_run_store_path
    except Exception:
        return ()
    try:
        path = tool_run_store_path()
    except Exception:
        return ()
    token: list[object] = []
    for candidate in (path, path.parent / f"{path.name}-wal"):
        try:
            stat = candidate.stat()
            token.append((str(candidate), stat.st_mtime_ns, stat.st_size))
        except OSError:
            token.append((str(candidate), None))
    return tuple(token)


__all__ = ["VIEWS", "store_token"]
