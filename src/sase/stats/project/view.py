"""Decode the wire once, retaining its exact JSON payload for both surfaces."""

from __future__ import annotations

from collections.abc import Collection
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass, replace
from functools import cache
from types import UnionType
from typing import Any, get_args, get_origin, get_type_hints

from sase.project_display_names import ProjectDisplaySnapshot

from .models import (
    ProjectStatsCoverage,
    ProjectStatsIssue,
    ProjectStatsModel,
    ProjectStatsPatch,
    ProjectStatsPortfolio,
    ProjectStatsProject,
    ProjectStatsRepo,
)
from .query import ProjectStatsFacet, ProjectStatsGrouping, ProjectStatsQuery


@dataclass(frozen=True, slots=True)
class ProjectStatsView:
    """Presentation snapshot; raw data is an independent JSON-safe wire copy."""

    query: ProjectStatsQuery
    projects: tuple[ProjectStatsProject, ...]
    portfolio: ProjectStatsPortfolio
    issues: tuple[ProjectStatsIssue, ...]
    fingerprint: str
    machine: str
    generated_at: str
    timezone: str
    facets: frozenset[ProjectStatsFacet]
    display_snapshot: ProjectDisplaySnapshot
    data: dict[str, Any]

    @property
    def repos(self) -> tuple[ProjectStatsRepo, ...]:
        return tuple(repo for project in self.projects for repo in project.repos)

    @property
    def models(self) -> tuple[ProjectStatsModel, ...]:
        return self.portfolio.models

    @property
    def patches(self) -> tuple[ProjectStatsPatch, ...]:
        return tuple(patch for project in self.projects for patch in project.patches)

    @property
    def coverage(self) -> ProjectStatsCoverage:
        return self.portfolio.coverage

    @property
    def effective_group_by(self) -> ProjectStatsGrouping:
        return self.query.group_by or (
            "model" if len(self.projects) == 1 else "project"
        )

    @property
    def code_pending(self) -> bool:
        return "code" not in self.facets

    @property
    def provider_subtotals(self) -> tuple[ProjectStatsModel, ...]:
        """Group already-deduplicated portfolio model rows for display."""
        groups: dict[tuple[str, str | None], list[ProjectStatsModel]] = {}
        for row in self.models:
            groups.setdefault((row.kind, row.provider), []).append(row)
        totals = []
        for (kind, provider), rows in groups.items():
            totals.append(
                ProjectStatsModel(
                    kind=kind,
                    provider=provider,
                    commits=sum(row.commits for row in rows),
                    plans=_nullable_sum([row.plans for row in rows]),
                    plans_epic=_nullable_sum([row.plans_epic for row in rows]),
                    plans_tale=_nullable_sum([row.plans_tale for row in rows]),
                    unknown_reasons=tuple(
                        sorted(
                            {reason for row in rows for reason in row.unknown_reasons}
                        )
                    ),
                )
            )
        return tuple(
            sorted(totals, key=lambda row: (-row.commits, row.provider or "", row.kind))
        )


def build_project_stats_view(
    data: dict[str, Any],
    query: ProjectStatsQuery,
    *,
    machine: str,
    generated_at: str,
    timezone: str,
    facets: Collection[ProjectStatsFacet],
    display_snapshot: ProjectDisplaySnapshot,
    issues: tuple[dict[str, Any], ...] = (),
) -> ProjectStatsView:
    """Project known fields into immutable records without altering raw JSON."""
    projects = tuple(
        replace(
            _decode(ProjectStatsProject, row),
            label=display_snapshot.get(row["key"], row["label"]),
        )
        for row in data["projects"]
    )
    return ProjectStatsView(
        query=query,
        projects=projects,
        portfolio=_decode(ProjectStatsPortfolio, data["portfolio"]),
        issues=tuple(
            _decode(ProjectStatsIssue, row) for row in (*data["issues"], *issues)
        ),
        fingerprint=data["fingerprint"],
        machine=machine,
        generated_at=generated_at,
        timezone=timezone,
        facets=frozenset(facets),
        display_snapshot=display_snapshot,
        data=deepcopy(data),
    )


@cache
def _field_types(cls: type) -> dict[str, Any]:
    return get_type_hints(cls)


def _decode(annotation: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = get_origin(annotation)
    if origin is UnionType:
        member = next(item for item in get_args(annotation) if item is not type(None))
        return _decode(member, value)
    if origin is tuple:
        return tuple(_decode(get_args(annotation)[0], item) for item in value)
    if isinstance(annotation, type) and is_dataclass(annotation):
        hints = _field_types(annotation)
        return annotation(
            **{
                field.name: _decode(hints[field.name], value[field.name])
                for field in fields(annotation)
                if field.name in value
            }
        )
    return value


def _nullable_sum(values: list[int | None]) -> int | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None
