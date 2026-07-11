"""Classify persisted diff artifacts for the Agents-tab file-change badge."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from sase.diff_paths import changed_files_from_diff

DiffBadgeCacheKey = tuple[str, int, int]

_diff_badge_cache: dict[DiffBadgeCacheKey, bool] = {}
_diff_badge_cache_lock = Lock()

_SDD_PLAN_DIRS = frozenset({"prompts", "plans", "tales", "epics"})


def _path_segments(path: str) -> list[str]:
    return [part for part in path.replace("\\", "/").split("/") if part]


def _is_plan_prompt_bookkeeping_path(path: str) -> bool:
    segments = _path_segments(path)
    for idx, segment in enumerate(segments[:-1]):
        if segment == "sdd" and segments[idx + 1] in _SDD_PLAN_DIRS:
            return True

    basename = segments[-1] if segments else ""
    return (
        basename.startswith("sase_plan_")
        and basename.endswith(".md")
        and len(basename) > len("sase_plan_.md")
    )


def diff_text_has_real_edits(diff_text: str) -> bool:
    """Return False only when every changed path is plan/prompt bookkeeping.

    Shared by the persisted-diff classifier (:func:`diff_has_real_edits`) and
    the live workspace hint. Empty or unparsed diff text fails open (True) so
    an unusual diff keeps the historical "diff means pencil" behavior.
    """
    changed_files = changed_files_from_diff(diff_text)
    if not changed_files:
        return True
    return any(not _is_plan_prompt_bookkeeping_path(path) for path in changed_files)


def diff_has_real_edits(diff_path: str) -> bool:
    """Return False only when a diff touches known plan/prompt bookkeeping.

    Error cases intentionally fail open so a row with an unreadable or unusual
    diff keeps the historical "diff_path means pencil" behavior.
    """
    expanded = os.path.abspath(os.path.expanduser(diff_path))
    try:
        st = os.stat(expanded)
    except OSError:
        return True

    key = (expanded, st.st_mtime_ns, st.st_size)
    with _diff_badge_cache_lock:
        cached = _diff_badge_cache.get(key)
        if cached is not None:
            return cached

    try:
        diff_text = Path(expanded).read_text(encoding="utf-8", errors="ignore")
        result = diff_text_has_real_edits(diff_text)
    except Exception:
        result = True

    with _diff_badge_cache_lock:
        _diff_badge_cache[key] = result
    return result
