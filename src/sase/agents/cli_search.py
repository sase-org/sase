"""``sase agent search`` over the historical agent catalog."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.ace.query.limit_token import LimitTokenError, apply_limit, extract_limit
from sase.ace.query.profile_reference_support import ProfileQueryError
from sase.agents.catalog import AgentCatalogRow, build_agent_catalog_snapshot
from sase.agents.catalog._query import (
    agent_catalog_rows_query_entries,
    agent_catalog_runtime_seconds,
    agent_catalog_stable_id,
)
from sase.agents.status_style import agent_status_text
from sase.core.query_profile_corpus_facade import (
    compile_artifact_query_index,
    evaluate_artifact_query_many,
)
from sase.main.parser_agent_search import DEFAULT_AGENT_SEARCH_LIMIT
from sase.project_display_names import (
    ProjectRefDisplaySnapshot,
    load_project_ref_display_snapshot,
)

_HIDDEN_KEY_RE = re.compile(r"(?<![A-Za-z0-9_-])hidden\s*:", re.IGNORECASE)


def handle_agents_search(args: argparse.Namespace) -> int:
    """Render the historical agent catalog search view."""
    query = _query_from_args(getattr(args, "query", None))
    limit = getattr(args, "limit", None)
    project = getattr(args, "project", None)
    as_json = bool(getattr(args, "json", False))

    project_ref_display = load_project_ref_display_snapshot()
    snapshot = build_agent_catalog_snapshot()
    rows = tuple(
        row
        for row in snapshot.rows
        if _row_matches_project(row, project, project_ref_display)
    )
    try:
        matched_rows, matched_total, cap, truncated = _evaluate_rows(
            query,
            rows,
            limit=limit,
            project_ref_display=project_ref_display,
        )
    except (LimitTokenError, ProfileQueryError, ValueError) as exc:
        Console(stderr=True).print(f"[bold red]error:[/bold red] {exc}")
        return 2

    if as_json:
        _print_json(matched_rows, project_ref_display=project_ref_display)
        return 0

    _print_pretty(
        matched_rows,
        total=len(rows),
        matched_total=matched_total,
        cap=cap,
        query=query,
        project_ref_display=project_ref_display,
    )
    return 0


def _evaluate_rows(
    query: str,
    rows: tuple[AgentCatalogRow, ...],
    *,
    limit: int | None,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> tuple[tuple[AgentCatalogRow, ...], int, int | None, bool]:
    profile = _agents_profile()
    remainder, query_cap = extract_limit(query)
    has_query_limit = remainder != query
    match_query = _presentation_scoped_query(remainder)
    index = compile_artifact_query_index(
        pane_id="agents",
        generation=1,
        profile=profile,
        entries=agent_catalog_rows_query_entries(
            rows, project_ref_display=project_ref_display
        ),
    )
    result = evaluate_artifact_query_many(match_query, index)
    rows_by_id = {agent_catalog_stable_id(row): row for row in rows}
    matched = tuple(
        rows_by_id[row_id] for row_id in result.matched_row_ids if row_id in rows_by_id
    )
    cap = _effective_limit(limit, query_cap=query_cap, has_query_limit=has_query_limit)
    limited, truncated = apply_limit(matched, cap)
    return limited, len(matched), cap, truncated


def _agents_profile() -> Any:
    from sase.ace.query_profile.pane_registry import compiled_profile_for_builtin_pane

    profile = compiled_profile_for_builtin_pane("agents")
    if profile is None:
        raise ValueError("built-in agents query profile is not registered")
    return profile


def _effective_limit(
    limit: int | None,
    *,
    query_cap: int | None,
    has_query_limit: bool,
) -> int | None:
    if limit is not None:
        return None if limit == 0 else limit
    if has_query_limit:
        return query_cap
    return DEFAULT_AGENT_SEARCH_LIMIT


def _presentation_scoped_query(query: str) -> str:
    terms: list[str] = []
    if not _mentions_hidden(query):
        terms.append("NOT hidden:true")
    if "workflow-child" not in query.casefold():
        terms.append("NOT kind:workflow-child")
    stripped = query.strip()
    if stripped:
        terms.append(f"({stripped})")
    return " AND ".join(terms)


def _mentions_hidden(query: str) -> bool:
    return _HIDDEN_KEY_RE.search(query) is not None


def _row_matches_project(
    row: AgentCatalogRow,
    project: str | None,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> bool:
    if not project:
        return True
    row_values = _project_values(row.project, project_ref_display)
    if not row_values:
        return False
    requested = _project_values(
        project_ref_display.project_key_for_ref(project) or project,
        project_ref_display,
    )
    requested = (*requested, project)
    wanted = {item.casefold() for item in requested if item}
    return any(item.casefold() in wanted for item in row_values)


def _project_values(
    project: str | None,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> tuple[str, ...]:
    if not project:
        return ()
    values = [project]
    label = project_ref_display.label_for_ref(project)
    if label and label.casefold() != project.casefold():
        values.append(label)
    return tuple(values)


def _query_from_args(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, Sequence):
        return " ".join(str(item) for item in raw).strip()
    return str(raw).strip()


def _print_json(
    rows: Sequence[AgentCatalogRow],
    *,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> None:
    payload = [_row_json(row, project_ref_display=project_ref_display) for row in rows]
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _row_json(
    row: AgentCatalogRow,
    *,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> dict[str, object]:
    return {
        "name": row.name,
        "canonical_global_name": row.canonical_global_name,
        "kind": list(row.kind),
        "project": row.project,
        "project_display": project_ref_display.label_for_ref(row.project),
        "state": row.state,
        "status": _status(row),
        "hidden": row.hidden,
        "dismissed": row.dismissed,
        "revivable": row.revivable,
        "attention": row.attention,
        "retry": row.retry,
        "attempt": row.retry_attempt,
        "family": row.family,
        "role": row.role,
        "clan": row.clan,
        "tribe": row.tribe,
        "workflow": row.workflow,
        "parent": row.parent_timestamp,
        "model": row.model,
        "provider": row.llm_provider,
        "patch": row.patch,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "runtime_seconds": agent_catalog_runtime_seconds(row),
        "raw_suffix": row.raw_suffix,
        "artifacts_dir": row.artifacts_dir,
        "bundle_path": row.bundle_path,
        "from_artifact_index": row.from_artifact_index,
        "from_dismissed_archive": row.from_dismissed_archive,
        "has_collision_history": row.has_collision_history,
    }


def _print_pretty(
    rows: Sequence[AgentCatalogRow],
    *,
    total: int,
    matched_total: int,
    cap: int | None,
    query: str,
    project_ref_display: ProjectRefDisplaySnapshot,
) -> None:
    console = Console()
    count_label = f"{len(rows)}"
    if cap is not None:
        count_label = f"{len(rows)} of {matched_total if matched_total else len(rows)}"
    title = f"Agent Catalog Search ({count_label}, {total} scoped)"
    if not rows:
        hint = (
            "No agent catalog rows matched."
            if query.strip()
            else "No agent catalog rows in the default presentation scope."
        )
        console.print(Panel(Text(hint, style="dim"), title=title, border_style="cyan"))
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("NAME", style="bold")
    table.add_column("KIND")
    table.add_column("PROJECT")
    table.add_column("STATE")
    table.add_column("STATUS")
    table.add_column("MODEL")
    table.add_column("PROVIDER")
    table.add_column("STARTED")
    table.add_column("FLAGS")

    for row in rows:
        table.add_row(
            row.name,
            ", ".join(row.kind),
            project_ref_display.label_for_ref(row.project) or "-",
            row.state or "-",
            _status_text(row),
            row.model or "-",
            row.llm_provider or "-",
            _short_date(row.started_at),
            _flags(row),
        )

    console.print(Panel(table, title=title, border_style="cyan"))


def _status(row: AgentCatalogRow) -> str | None:
    if not row.status:
        return None
    text = row.status.strip()
    return text.upper() if text else None


def _status_text(row: AgentCatalogRow) -> Text:
    status = _status(row)
    if status is None:
        return Text("-")
    return agent_status_text(status)


def _short_date(value: str | None) -> str:
    if not value:
        return "-"
    text = value.replace("T", " ")
    return text[:16]


def _flags(row: AgentCatalogRow) -> str:
    labels: list[str] = []
    if row.revivable:
        labels.append("revivable")
    if row.attention:
        labels.append("attention")
    if row.retry:
        labels.append("retry")
    if row.hidden:
        labels.append("hidden")
    if not row.from_artifact_index and not row.from_dismissed_archive:
        labels.append("thin")
    return ", ".join(labels) if labels else "-"


__all__ = ["handle_agents_search"]
