"""Query-row adapter for the Textual-free agent catalog."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sase.ace.query.profile_evaluator import (
    ArtifactQueryRow,
    ProfileFieldValue,
    coerce_artifact_query_date_value,
)
from sase.core.time import get_timezone
from sase.project_display_names import ProjectRefDisplaySnapshot

from ._models import AgentCatalogRow, AgentCatalogSnapshot


@dataclass(frozen=True, slots=True)
class AgentCatalogLinkFacets:
    """Artifact-link facets attached to one agent catalog row."""

    relations: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    count: int = 0

    @property
    def linked(self) -> bool:
        """Return whether at least one artifact-link row touches the agent."""
        return self.count > 0


def agent_catalog_stable_id(row: AgentCatalogRow) -> str:
    """Return the stable query identity for one catalog row."""
    return f"agent:{row.name}"


def agent_catalog_query_entries(
    snapshot: AgentCatalogSnapshot,
    *,
    project_ref_display: ProjectRefDisplaySnapshot | None = None,
    link_facets: Mapping[str, AgentCatalogLinkFacets] | None = None,
) -> tuple[ArtifactQueryRow, ...]:
    """Return profile-driven query entries for every row in *snapshot*."""
    return agent_catalog_rows_query_entries(
        snapshot.rows,
        project_ref_display=project_ref_display,
        link_facets=link_facets,
    )


def agent_catalog_rows_query_entries(
    rows: Iterable[AgentCatalogRow],
    *,
    project_ref_display: ProjectRefDisplaySnapshot | None = None,
    link_facets: Mapping[str, AgentCatalogLinkFacets] | None = None,
) -> tuple[ArtifactQueryRow, ...]:
    """Return profile-driven query entries for the provided catalog rows."""
    display = project_ref_display or ProjectRefDisplaySnapshot()
    return tuple(
        agent_catalog_query_entry(
            row,
            project_ref_display=display,
            link_facets=link_facets,
        )
        for row in rows
    )


def agent_catalog_query_entry(
    row: AgentCatalogRow,
    *,
    project_ref_display: ProjectRefDisplaySnapshot | None = None,
    link_facets: Mapping[str, AgentCatalogLinkFacets] | None = None,
) -> ArtifactQueryRow:
    """Return one row shaped for ``compile_artifact_query_index``."""
    display = project_ref_display or ProjectRefDisplaySnapshot()
    link_facet = (link_facets or {}).get(row.name)
    status = _status(row.status)
    project_values = _project_values(row.project, display)
    label_values = _label_values(row, project_values=project_values, status=status)
    text_values = _text_values(row, label_values=label_values)
    started_epoch = (
        coerce_artifact_query_date_value(row.started_at) if row.started_at else None
    )
    finished_epoch = _finished_query_timestamp(row.finished_at)
    fields: dict[str, tuple[ProfileFieldValue, ...]] = {}
    _add_field(fields, "name", _distinct(row.name, row.canonical_global_name))
    _add_field(fields, "kind", row.kind)
    _add_field(fields, "project", project_values)
    _add_field(fields, "state", row.state)
    _add_field(fields, "status", status)
    _add_field(fields, "hidden", row.hidden)
    _add_field(fields, "dismissed", row.dismissed)
    _add_field(fields, "revivable", row.revivable)
    _add_field(fields, "historically_viewable", row.historically_viewable)
    _add_field(fields, "durably_revivable", row.durably_revivable)
    _add_field(fields, "restartable", row.restartable)
    _add_field(fields, "attention", row.attention)
    _add_field(fields, "retry", row.retry)
    _add_field(fields, "linked", bool(link_facet and link_facet.linked))
    if link_facet is not None:
        _add_field(fields, "relation", link_facet.relations)
        _add_field(fields, "artifact", link_facet.artifacts)
    _add_field(fields, "label", label_values)
    _add_field(fields, "text", text_values)
    _add_if_present(fields, "family", row.family)
    _add_if_present(fields, "role", row.role)
    _add_if_present(fields, "clan", row.clan)
    _add_if_present(fields, "tribe", row.tribe)
    _add_if_present(fields, "workflow", row.workflow)
    _add_if_present(fields, "parent", row.parent_timestamp)
    _add_if_present(fields, "model", row.model)
    _add_if_present(fields, "provider", row.llm_provider)
    _add_if_present(fields, "patch", row.patch)
    _add_if_present(fields, "attempt", row.retry_attempt)
    if started_epoch is not None:
        _add_field(fields, "since", started_epoch)
        _add_field(fields, "until", started_epoch)
    if finished_epoch is not None:
        _add_field(fields, "after", finished_epoch)
        _add_field(fields, "before", finished_epoch)
    if (
        runtime_seconds := _runtime_seconds(
            started_at=_runtime_timestamp(row.started_at),
            finished_at=_runtime_timestamp(row.finished_at),
        )
    ) is not None:
        _add_field(fields, "min", runtime_seconds)
        _add_field(fields, "max", runtime_seconds)

    return ArtifactQueryRow(
        stable_id=agent_catalog_stable_id(row),
        fields=fields,
        searchable_text="\n".join(text_values),
        predicates=_predicates(status),
    )


def agent_catalog_runtime_seconds(row: AgentCatalogRow) -> int | None:
    """Return finished runtime seconds when both timestamps are available."""
    return _runtime_seconds(
        started_at=_runtime_timestamp(row.started_at),
        finished_at=_runtime_timestamp(row.finished_at),
    )


def build_agent_catalog_link_facets(
    rows: Iterable[AgentCatalogRow],
    link_rows: Iterable[Mapping[str, Any]],
) -> Mapping[str, AgentCatalogLinkFacets]:
    """Return artifact-link query facets keyed by agent catalog row name."""

    catalog_rows = tuple(rows)
    agent_names = _agent_ref_candidate_index(catalog_rows)
    relations: dict[str, set[str]] = {}
    artifacts: dict[str, set[str]] = {}
    counts: dict[str, int] = {}

    for raw in link_rows:
        source_ref = _normalized_link_ref(raw.get("source_ref"))
        target_ref = _normalized_link_ref(raw.get("target_ref"))
        if not source_ref or not target_ref:
            continue
        relation = str(raw.get("relation") or "").strip()
        source_name = _agent_name_for_link_ref(source_ref, agent_names)
        target_name = _agent_name_for_link_ref(target_ref, agent_names)
        touched: set[str] = set()
        if source_name is not None:
            _record_link_facet(
                source_name,
                other_ref=target_ref,
                relation=relation,
                relations=relations,
                artifacts=artifacts,
            )
            touched.add(source_name)
        if target_name is not None:
            _record_link_facet(
                target_name,
                other_ref=source_ref,
                relation=relation,
                relations=relations,
                artifacts=artifacts,
            )
            touched.add(target_name)
        for name in touched:
            counts[name] = counts.get(name, 0) + 1

    return {
        name: AgentCatalogLinkFacets(
            relations=tuple(sorted(relations.get(name, ()))),
            artifacts=tuple(sorted(artifacts.get(name, ()))),
            count=count,
        )
        for name, count in counts.items()
    }


def _agent_ref_candidate_index(rows: tuple[AgentCatalogRow, ...]) -> dict[str, str]:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_lookup_candidates,
    )

    identity = AgentIdentitySnapshot.current()
    index: dict[str, str] = {}
    for row in rows:
        _remember_agent_ref_candidate(index, row.name, row.name, replace=True)
        _remember_agent_ref_candidate(
            index, row.canonical_global_name, row.name, replace=True
        )
    for row in rows:
        for value in (row.name, row.canonical_global_name):
            if not value:
                continue
            for candidate in current_owner_agent_name_lookup_candidates(
                value, identity
            ):
                _remember_agent_ref_candidate(index, candidate, row.name)
    return index


def _remember_agent_ref_candidate(
    index: dict[str, str],
    candidate: str | None,
    row_name: str,
    *,
    replace: bool = False,
) -> None:
    text = (candidate or "").strip()
    if not text:
        return
    if replace or text not in index:
        index[text] = row_name


def _agent_name_for_link_ref(
    ref: str,
    agent_names: Mapping[str, str],
) -> str | None:
    kind, sep, payload = ref.partition(":")
    if sep != ":" or kind != "agent" or not payload:
        return None
    return agent_names.get(payload)


def _record_link_facet(
    name: str,
    *,
    other_ref: str,
    relation: str,
    relations: dict[str, set[str]],
    artifacts: dict[str, set[str]],
) -> None:
    if relation:
        relations.setdefault(name, set()).add(relation)
    if other_ref:
        artifacts.setdefault(name, set()).add(other_ref)


def _normalized_link_ref(value: object) -> str:
    text = str(value or "").strip().removeprefix("@").split("#", 1)[0].strip()
    return text


def _status(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text.upper() if text else None


def _project_values(
    project: str | None,
    display: ProjectRefDisplaySnapshot,
) -> tuple[str, ...]:
    if not project:
        return ()
    return _distinct(project, display.label_for_ref(project))


def _label_values(
    row: AgentCatalogRow,
    *,
    project_values: tuple[str, ...],
    status: str | None,
) -> tuple[str, ...]:
    return _distinct(
        row.name,
        row.canonical_global_name,
        *project_values,
        row.state,
        status,
        row.model,
        row.llm_provider,
    )


def _text_values(
    row: AgentCatalogRow,
    *,
    label_values: tuple[str, ...],
) -> tuple[str, ...]:
    return _distinct(
        *label_values,
        *row.kind,
        row.family,
        row.role,
        row.clan,
        row.tribe,
        row.workflow,
        row.parent_timestamp,
        row.raw_suffix,
        row.artifacts_dir,
        row.bundle_path,
        row.patch,
        *row.missing_requirements,
    )


def _predicates(status: str | None) -> frozenset[str]:
    if status in {"RUNNING", "STARTING", "WAITING"}:
        return frozenset(("running_agent",))
    return frozenset()


def _add_field(
    fields: dict[str, tuple[ProfileFieldValue, ...]],
    key: str,
    value: ProfileFieldValue | tuple[ProfileFieldValue, ...] | None,
) -> None:
    if value is None:
        return
    values = value if isinstance(value, tuple) else (value,)
    if values:
        fields[key] = values


def _add_if_present(
    fields: dict[str, tuple[ProfileFieldValue, ...]],
    key: str,
    value: ProfileFieldValue | None,
) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    _add_field(fields, key, value)


def _runtime_seconds(
    *,
    started_at: float | None,
    finished_at: float | None,
) -> int | None:
    if started_at is None or finished_at is None:
        return None
    return max(0, int(finished_at - started_at))


def _runtime_timestamp(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        return float(value)
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=get_timezone())
    return parsed.timestamp()


def _finished_query_timestamp(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return coerce_artifact_query_date_value(value)


def _distinct(*values: object) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value)
        if not text:
            continue
        folded = text.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        result.append(text)
    return tuple(result)


__all__ = [
    "AgentCatalogLinkFacets",
    "agent_catalog_query_entries",
    "agent_catalog_query_entry",
    "agent_catalog_rows_query_entries",
    "agent_catalog_runtime_seconds",
    "agent_catalog_stable_id",
    "build_agent_catalog_link_facets",
]
