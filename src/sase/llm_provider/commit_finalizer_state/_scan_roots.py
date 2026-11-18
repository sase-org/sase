"""Scan-root enumeration shared by dirty-state collection and write guards.

:func:`commit_scan_roots` returns the normalized checkout paths the commit
finalizer scans, in scan order, without making any git status calls. It
uses the single shared enumeration in :mod:`_repository_candidates` so
detectors share the finalizer's effective eligibility and selection rules.
"""

from __future__ import annotations

from pathlib import Path

from ._repository_candidates import repository_candidates


def commit_scan_roots(
    project_dir: str,
    artifact_root: Path | None = None,
) -> tuple[str, ...]:
    """Return normalized scan roots in ``collect_dirty_state`` order.

    The roots are the main project dir, configured sibling target dirs with
    name-only opens resolved through sibling targets, opened external
    workspace dirs, and known SDD and agents-archive paths. The result is
    deduped with first-seen order preserved. This function makes no git
    status calls.
    """

    candidates, _ = repository_candidates(project_dir, artifact_root)
    ordered: list[str] = []
    seen: set[str] = set()
    for _name, path, _kind in candidates:
        if path and path not in seen:
            seen.add(path)
            ordered.append(path)
    return tuple(ordered)


__all__ = ["commit_scan_roots"]
