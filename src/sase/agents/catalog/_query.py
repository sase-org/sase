"""Query-row adapter for the Textual-free agent catalog."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sase.core.time import parse_local
from sase.project_display_names import ProjectRefDisplaySnapshot

from ._models import AgentCatalogRow, AgentCatalogSnapshot


def agent_catalog_stable_id(row: AgentCatalogRow) -> str:
    """Return the stable query identity for one catalog row."""
    return f"agent:{row.name}"


def agent_catalog_query_entries(
    snapshot: AgentCatalogSnapshot,
    *,
    project_ref_display: ProjectRefDisplaySnapshot | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return profile-driven query entries for every row in *snapshot*."""
    return agent_catalog_rows_query_entries(
        snapshot.rows, project_ref_display=project_ref_display
    )


def agent_catalog_rows_query_entries(
    rows: Iterable[AgentCatalogRow],
    *,
    project_ref_display: ProjectRefDisplaySnapshot | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return profile-driven query entries for the provided catalog rows."""
    display = project_ref_display or ProjectRefDisplaySnapshot()
    return tuple(
        agent_catalog_query_entry(row, project_ref_display=display) for row in rows
    )


def agent_catalog_query_entry(
    row: AgentCatalogRow,
    *,
    project_ref_display: ProjectRefDisplaySnapshot | None = None,
) -> dict[str, Any]:
    """Return one row shaped for ``compile_artifact_query_index``."""
    display = project_ref_display or ProjectRefDisplaySnapshot()
    fields: dict[str, object] = {
        "name": _distinct(row.name, row.canonical_global_name),
        "kind": row.kind,
        "project": _project_values(row.project, display),
        "state": row.state,
        "status": _status(row.status),
        "hidden": row.hidden,
        "dismissed": row.dismissed,
        "revivable": row.revivable,
        "attention": row.attention,
        "retry": row.retry,
        "label": _label_values(row, display),
        "text": _text_values(row, display),
    }
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
    if row.started_at:
        fields["since"] = (row.started_at,)
        fields["until"] = (row.started_at,)
    if row.finished_at is not None:
        finished_epoch = int(row.finished_at)
        fields["after"] = (finished_epoch,)
        fields["before"] = (finished_epoch,)
    if (runtime_seconds := agent_catalog_runtime_seconds(row)) is not None:
        fields["min"] = (runtime_seconds,)
        fields["max"] = (runtime_seconds,)

    return {
        "stable_id": agent_catalog_stable_id(row),
        "fields": fields,
        "searchable_text": "\n".join(str(item) for item in _text_values(row, display)),
        "predicates": _predicates(row),
    }


def agent_catalog_runtime_seconds(row: AgentCatalogRow) -> int | None:
    """Return finished runtime seconds when both timestamps are available."""
    if not row.started_at or row.finished_at is None:
        return None
    started = parse_local(row.started_at)
    finished = parse_local(row.finished_at)
    if started is None or finished is None:
        return None
    return max(0, int((finished - started).total_seconds()))


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
    display: ProjectRefDisplaySnapshot,
) -> tuple[str, ...]:
    return _distinct(
        row.name,
        row.canonical_global_name,
        *_project_values(row.project, display),
        row.state,
        _status(row.status),
        row.model,
        row.llm_provider,
    )


def _text_values(
    row: AgentCatalogRow,
    display: ProjectRefDisplaySnapshot,
) -> tuple[str, ...]:
    return _distinct(
        *_label_values(row, display),
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


def _predicates(row: AgentCatalogRow) -> tuple[str, ...]:
    status = _status(row.status)
    if status in {"RUNNING", "STARTING", "WAITING"}:
        return ("running_agent",)
    return ()


def _add_if_present(fields: dict[str, object], key: str, value: object) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    fields[key] = value


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
