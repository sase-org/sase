"""Kind -> provider dispatch for pre-argparse completion candidates.

Each provider's real dependencies (Rust bindings, display-name projection,
bead-store resolution) are imported inside its callable, never at module
scope, so requesting one kind never pays for the others -- and a kind with no
shipped provider costs nothing at all.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sase.completion.candidates.cache import (
    load_cached_candidates,
    store_cached_candidates,
)
from sase.completion.candidates.protocol import Candidate, filter_candidates
from sase.completion.kinds import ValueKind

_Fetch = Callable[[str | None], list[Candidate]]
_SourcePath = Callable[[str | None], "Path | None"]


def candidates_for(
    kind: str, prefix: str, *, project: str | None, limit: int
) -> list[Candidate]:
    """Return up to *limit* candidates for *kind* matching *prefix*.

    An unrecognized kind -- one with no ``ValueKind`` member or no shipped
    provider -- returns an empty list rather than raising, so a shell never
    sees a traceback for a kind this sase build does not know.
    """
    try:
        value_kind = ValueKind(kind)
    except ValueError:
        return []
    provider = _PROVIDERS.get(value_kind)
    if provider is None:
        return []

    fetch, source_path = provider
    cache_key = value_kind if project is None else f"{value_kind}__{project}"
    source_mtime = _safe_mtime(source_path(project))
    cached = load_cached_candidates(cache_key, source_mtime=source_mtime)
    if cached is None:
        cached = fetch(project)
        store_cached_candidates(cache_key, cached)
    return filter_candidates(cached, prefix, limit)


def _safe_mtime(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _project_source_path(_project: str | None) -> Path | None:
    from sase.core.paths import sase_projects_dir

    return sase_projects_dir()


def _project_candidates(_project: str | None) -> list[Candidate]:
    from sase.core.paths import sase_projects_dir
    from sase.core.project_lifecycle_facade import list_project_records
    from sase.project_display_names import ProjectDisplaySnapshot

    records = list_project_records(sase_projects_dir(), "all", include_home=True)
    snapshot = ProjectDisplaySnapshot.from_records(records)
    return [
        Candidate(snapshot.label_for(record.project_name), record.state)
        for record in records
    ]


def _resolve_beads_dir() -> Path | None:
    from sase.bead.cli_location import resolve_beads_location

    location = resolve_beads_location(Path.cwd(), require_existing=True)
    return None if location is None else location.beads_dir


def _bead_source_path(_project: str | None) -> Path | None:
    return _resolve_beads_dir()


def _bead_candidates(_project: str | None) -> list[Candidate]:
    beads_dir = _resolve_beads_dir()
    if beads_dir is None:
        return []
    from sase.core.bead_read_facade import list_issues

    return [Candidate(issue.id, issue.title) for issue in list_issues(beads_dir)]


_PROVIDERS: dict[ValueKind, tuple[_Fetch, _SourcePath]] = {
    ValueKind.PROJECT: (_project_candidates, _project_source_path),
    ValueKind.BEAD: (_bead_candidates, _bead_source_path),
}


__all__ = ["candidates_for"]
