"""Query-row adapter for the Textual-free agent catalog."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sase.ace.query.profile_evaluator import (
    ArtifactQueryRow,
    ProfileFieldValue,
    coerce_artifact_query_date_value,
)
from sase.core.time import get_timezone
from sase.project_display_names import ProjectRefDisplaySnapshot

from ._models import AgentCatalogRow, AgentCatalogSnapshot


def agent_catalog_stable_id(row: AgentCatalogRow) -> str:
    """Return the stable query identity for one catalog row."""
    return f"agent:{row.name}"


def agent_catalog_query_entries(
    snapshot: AgentCatalogSnapshot,
    *,
    project_ref_display: ProjectRefDisplaySnapshot | None = None,
) -> tuple[ArtifactQueryRow, ...]:
    """Return profile-driven query entries for every row in *snapshot*."""
    return agent_catalog_rows_query_entries(
        snapshot.rows, project_ref_display=project_ref_display
    )


def agent_catalog_rows_query_entries(
    rows: Iterable[AgentCatalogRow],
    *,
    project_ref_display: ProjectRefDisplaySnapshot | None = None,
) -> tuple[ArtifactQueryRow, ...]:
    """Return profile-driven query entries for the provided catalog rows."""
    display = project_ref_display or ProjectRefDisplaySnapshot()
    return tuple(
        agent_catalog_query_entry(row, project_ref_display=display) for row in rows
    )


def agent_catalog_query_entry(
    row: AgentCatalogRow,
    *,
    project_ref_display: ProjectRefDisplaySnapshot | None = None,
) -> ArtifactQueryRow:
    """Return one row shaped for ``compile_artifact_query_index``."""
    display = project_ref_display or ProjectRefDisplaySnapshot()
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
    _add_field(fields, "attention", row.attention)
    _add_field(fields, "retry", row.retry)
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
    "agent_catalog_query_entries",
    "agent_catalog_query_entry",
    "agent_catalog_rows_query_entries",
    "agent_catalog_runtime_seconds",
    "agent_catalog_stable_id",
]
