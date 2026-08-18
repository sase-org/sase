"""Catalog fetchers for SDD artifacts: beads and plans.

Both resolve their store by walking up from the current directory to a
repository root; see :mod:`sase.completion.candidates.catalog` for the import
contract.
"""

from __future__ import annotations

import os
from pathlib import Path

from sase.completion.candidates.catalog_support import dedupe
from sase.completion.candidates.protocol import Candidate

_REPO_MARKERS = (".git", ".hg", ".jj")


def _resolve_beads_dir() -> Path | None:
    env = os.environ.get("SASE_SDD_BEADS_DIR")
    if env:
        path = Path(env)
        return path if path.is_dir() else None
    try:
        current = Path.cwd()
    except OSError:
        return None
    for parent in (current, *current.parents):
        for candidate in (
            parent / "sdd" / "beads",
            parent / ".sase" / "sdd" / "beads",
        ):
            if candidate.is_dir():
                return candidate
        if any((parent / marker).exists() for marker in _REPO_MARKERS):
            break
    return None


def bead_source_path(_project: str | None) -> Path | None:
    """Return the cache-invalidation path for bead candidates."""
    return _resolve_beads_dir()


def bead_candidates(_project: str | None) -> list[Candidate]:
    """Return every bead id in the resolved bead store, with its title."""
    beads_dir = _resolve_beads_dir()
    if beads_dir is None:
        return []
    from sase.core.rust import require_rust_binding

    try:
        payload = require_rust_binding("bead_list")(str(beads_dir), None, None, None)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    candidates: list[Candidate] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        issue_id = str(item.get("id") or "")
        if not issue_id:
            continue
        candidates.append(Candidate(issue_id, str(item.get("title") or "")))
    return dedupe(candidates)


def plan_source_path(_project: str | None) -> Path | None:
    """Return the cache-invalidation path for plan candidates."""
    from sase.core.paths import sase_subdir

    return sase_subdir("plans")


def plan_candidates(_project: str | None) -> list[Candidate]:
    """Return canonical plan references from the home and repo plan roots."""
    from sase.core.paths import sase_subdir
    from sase.core.rust import require_rust_binding

    roots: list[Path] = [sase_subdir("plans")]
    try:
        cwd = Path.cwd()
    except OSError:
        cwd = None
    if cwd is not None:
        for parent in (cwd, *cwd.parents):
            for candidate in (
                parent / "sdd" / "plans",
                parent / ".sase" / "sdd" / "plans",
            ):
                if candidate.is_dir() and candidate not in roots:
                    roots.append(candidate)
            if any((parent / marker).exists() for marker in _REPO_MARKERS):
                break
    canonicalize = require_rust_binding("plan_reference_canonicalize")
    root_strings = [str(root) for root in roots]
    candidates: list[Candidate] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/*.md")):
            try:
                reference = canonicalize(str(path), root_strings)
            except Exception:
                reference = None
            if not reference:
                reference = f"plan:{path.parent.name}/{path.name}"
            candidates.append(Candidate(str(reference), path.stem))
    return dedupe(candidates)


__all__ = [
    "bead_candidates",
    "bead_source_path",
    "plan_candidates",
    "plan_source_path",
]
