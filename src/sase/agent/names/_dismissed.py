"""Dismissed-name lifecycle helpers (sase-10 phase 1).

Allocate collision-free dismissed names and scan persistent state for
already-taken ``YYmmdd.<base>`` entries.
"""

import json
from datetime import date, datetime
from pathlib import Path

from sase.agent.names._common import (
    add_dismissed_prefix,
    is_dismissed_prefixed,
    strip_dismissed_prefix,
)


def allocate_dismissed_name(
    base: str,
    completion_date: date | datetime,
    *,
    taken: set[str] | None = None,
) -> str:
    """Allocate a unique dismissed name for *base* completing on *completion_date*.

    Returns ``YYmmdd.<base>`` when free; otherwise appends ``.2``, ``.3``,
    ... until an unused name is found. *base* may itself be dismissal-prefixed
    — the prefix is stripped first so callers can pass the live name or an
    already-dismissed name interchangeably.

    The collision source defaults to :func:`collect_dismissed_taken_names`,
    which scans dismissed bundles plus any historical artifact metadata that
    still carries a prefixed name. Pass *taken* explicitly for tests or when
    a richer in-memory candidate set is already known (e.g. batch dismissal).
    """
    if is_dismissed_prefixed(base):
        base = strip_dismissed_prefix(base)
    pool = collect_dismissed_taken_names() if taken is None else set(taken)
    primary = add_dismissed_prefix(base, completion_date)
    if primary not in pool:
        return primary
    n = 2
    while True:
        candidate = f"{primary}.{n}"
        if candidate not in pool:
            return candidate
        n += 1


def collect_dismissed_taken_names() -> set[str]:
    """Return dismissed-prefixed names already in use across persistent state.

    Scans:

    - dismissed bundle files for ``agent_name``/``cl_name`` fields that carry
      a ``YYmmdd.`` prefix
    - artifact ``agent_meta.json`` and ``done.json`` for ``name`` /
      ``workflow_name`` fields that carry a prefix (covers crashed or
      partially restored history that never made it into a bundle)

    Errors during scanning are swallowed; the worst case is an
    underestimated collision set, which the caller will detect on the next
    allocation.
    """
    taken: set[str] = set()
    _collect_taken_from_bundles(taken)
    _collect_taken_from_artifacts(taken)
    return taken


def _collect_taken_from_bundles(taken: set[str]) -> None:
    try:
        from sase.ace.dismissed_agents import _DISMISSED_BUNDLES_DIR
    except Exception:
        return

    bundles_dir: Path = _DISMISSED_BUNDLES_DIR
    if not bundles_dir.is_dir():
        return

    try:
        candidates = list(bundles_dir.rglob("*.json"))
    except OSError:
        return

    for filepath in candidates:
        if not filepath.is_file():
            continue
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for key in ("agent_name", "cl_name"):
            value = data.get(key)
            if isinstance(value, str) and is_dismissed_prefixed(value):
                taken.add(value)


def _collect_taken_from_artifacts(taken: set[str]) -> None:
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.is_dir():
        return

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.is_dir():
            continue
        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue
            for fname in ("agent_meta.json", "done.json"):
                p = artifact_dir / fname
                if not p.is_file():
                    continue
                try:
                    with open(p, encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue
                for key in ("name", "workflow_name"):
                    value = data.get(key)
                    if isinstance(value, str) and is_dismissed_prefixed(value):
                        taken.add(value)
