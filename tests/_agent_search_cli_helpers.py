from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sase.agents.catalog import AgentCatalogRow, AgentCatalogSnapshot
from sase.project_display_names import ProjectDisplaySnapshot, ProjectRefDisplaySnapshot
from tests._agent_catalog_helpers import make_agent_catalog_row


def patch_sources(
    monkeypatch: Any,
    snapshot: AgentCatalogSnapshot,
    *,
    link_rows: tuple[dict[str, object], ...] = (),
) -> None:
    from sase.agents import cli_search

    display = ProjectRefDisplaySnapshot(
        display_snapshot=ProjectDisplaySnapshot({"gh_sase-org__sase": "sase"}),
        aliases={"sase": "gh_sase-org__sase"},
    )
    monkeypatch.setattr(cli_search, "build_agent_catalog_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        cli_search, "load_project_ref_display_snapshot", lambda: display
    )
    monkeypatch.setattr(
        cli_search,
        "load_artifact_links_snapshot",
        lambda _project: SimpleNamespace(rows=link_rows),
    )


def make_snapshot(
    *rows: AgentCatalogRow,
    diagnostics: tuple[str, ...] = (),
) -> AgentCatalogSnapshot:
    return AgentCatalogSnapshot(
        rows=tuple(rows),
        registry_entry_count=len(rows),
        artifact_index_row_count=sum(1 for row in rows if row.from_artifact_index),
        dismissed_summary_count=sum(1 for row in rows if row.from_dismissed_archive),
        enriched_count=sum(
            1 for row in rows if row.from_artifact_index or row.from_dismissed_archive
        ),
        thin_count=sum(
            1
            for row in rows
            if not row.from_artifact_index and not row.from_dismissed_archive
        ),
        facets={},
        diagnostics=diagnostics,
    )


def make_row(name: str, **overrides: Any) -> AgentCatalogRow:
    values: dict[str, Any] = {
        "canonical_global_name": f"bbugyi200.athena.{name}",
        "kind": ("agent",),
        "project": "gh_sase-org__sase",
        "state": "active",
        "raw_suffix": "20260801000000",
        "artifacts_dir": f"/artifacts/{name}",
        "model": "gpt-5",
        "llm_provider": "codex",
        "status": "DONE",
        "started_at": "2026-08-01T00:00:00+00:00",
        "from_artifact_index": True,
    }
    values.update(overrides)
    return make_agent_catalog_row(name, **values)


def epoch(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()
