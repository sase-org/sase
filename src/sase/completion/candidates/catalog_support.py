"""Helpers shared by the completion candidate catalog modules.

Every ``catalog_*`` module lives under the import discipline documented in
:mod:`sase.completion.candidates.catalog`: module scope stays on stdlib plus
this package, and each fetcher imports its real dependencies inside the
function so requesting one kind never pays for the others.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sase.completion.candidates.protocol import Candidate

if TYPE_CHECKING:
    from sase.core.project_lifecycle_wire import ProjectRecordWire
    from sase.project_display_names import ProjectDisplaySnapshot


def dedupe(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Return *candidates* without empty or repeated values, order preserved."""
    seen: set[str] = set()
    unique: list[Candidate] = []
    for candidate in candidates:
        if candidate.value in seen or not candidate.value:
            continue
        seen.add(candidate.value)
        unique.append(candidate)
    return unique


def project_records_and_snapshot(
    project: str | None,
) -> tuple[list[ProjectRecordWire], ProjectDisplaySnapshot]:
    """Return lifecycle records for *project* (or all) plus their display names."""
    from sase.core.paths import sase_projects_dir
    from sase.core.project_lifecycle_facade import list_project_records
    from sase.core.project_lifecycle_wire import effective_project_name
    from sase.project_display_names import ProjectDisplaySnapshot

    records = list_project_records(sase_projects_dir(), "all", include_home=True)
    if project is not None:
        records = [
            record
            for record in records
            if record.project_name == project
            or effective_project_name(record) == project
        ]
    return records, ProjectDisplaySnapshot.from_records(records)


__all__ = ["dedupe", "project_records_and_snapshot"]
