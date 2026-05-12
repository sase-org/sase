"""Tests for the archive-backed revive modal."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sase.ace.agent_query.archive_planner import (
    ArchiveQueryError,
    ArchiveQueryPage,
    ArchiveQueryResult,
)
from sase.ace.dismissed_bundle_index import rebuild_index
from sase.ace.tui.actions.agents._revive import _ScopedArchiveQueryProvider
from sase.ace.tui.modals.project_select_modal import SelectionItem
from sase.ace.tui.modals.revive_agent_modal import DismissedAgentSelectModal

from tests._agent_revive_helpers import make_agent


def _result(**overrides: object) -> ArchiveQueryResult:
    values: dict[str, object] = {
        "agent_id": "agent-id",
        "raw_suffix": "20260512120000",
        "bundle_path": "/tmp/bundle.json",
        "cl_name": "default_cl",
        "agent_name": "default_agent",
        "status": "DONE",
        "start_time": "2026-05-12T12:00:00",
        "dismissed_at": "2026-05-12T12:30:00",
        "revived_at": None,
        "project_name": "sase",
        "model": "gpt-5.5",
        "runtime": "codex",
        "llm_provider": "codex",
        "step_index": None,
        "step_name": None,
        "step_type": None,
        "retry_attempt": 0,
        "is_workflow_child": False,
    }
    values.update(overrides)
    return ArchiveQueryResult(**values)  # type: ignore[arg-type]


@dataclass
class _Provider:
    pages: dict[str, ArchiveQueryPage]
    hydrated: list[str]

    def search(
        self,
        query: str,
        *,
        limit: int,
        cursor: int | None = None,
    ) -> ArchiveQueryPage:
        if query == "hidden:true":
            raise ArchiveQueryError("hidden: is only available for live agent queries")
        return self.pages[query]

    def hydrate(self, result: ArchiveQueryResult) -> list[object]:
        self.hydrated.append(result.agent_id)
        return [
            make_agent(
                cl_name=result.cl_name,
                raw_suffix=result.raw_suffix,
                agent_name=result.agent_name,
                status=result.status,
            )
        ]


def test_archive_query_error_preserves_previous_results() -> None:
    hit = _result(agent_id="hit", cl_name="failed_cl", status="FAILED")
    provider = _Provider(
        pages={"status:failed": ArchiveQueryPage(results=[hit], next_cursor=None)},
        hydrated=[],
    )
    modal = DismissedAgentSelectModal([], archive_query_provider=provider)

    assert modal.refresh_archive_query("status:failed") is True
    assert modal.refresh_archive_query("hidden:true") is False

    assert [entry.archive_result.cl_name for entry in modal._entries] == ["failed_cl"]
    assert "only available for live agent queries" in (modal._query_error or "")


def test_archive_entries_hydrate_only_on_demand() -> None:
    hit = _result(agent_id="hit", cl_name="lazy_cl")
    provider = _Provider(
        pages={"": ArchiveQueryPage(results=[hit], next_cursor=None)},
        hydrated=[],
    )
    modal = DismissedAgentSelectModal([], archive_query_provider=provider)

    modal.refresh_archive_query("")
    assert provider.hydrated == []

    agent = modal._hydrate_entry(modal._entries[0])

    assert agent is not None
    assert agent.cl_name == "lazy_cl"
    assert provider.hydrated == ["hit"]


def _write_bundle(root: Path, **overrides: object) -> None:
    raw_suffix = str(overrides.get("raw_suffix", "20260512120000"))
    bundle: dict[str, object] = {
        "raw_suffix": raw_suffix,
        "agent_type": "run",
        "cl_name": "default_cl",
        "agent_name": "default_agent",
        "status": "DONE",
        "start_time": "2026-05-12T12:00:00",
        "dismissed_at": "2026-05-12T12:30:00",
        "project_file": "/tmp/projects/sase/sase.sase",
        "model": "gpt-5.5",
        "llm_provider": "codex",
        "runtime": "codex",
    }
    bundle.update(overrides)
    shard = root / raw_suffix[:6]
    shard.mkdir(parents=True, exist_ok=True)
    (shard / f"{raw_suffix}.json").write_text(json.dumps(bundle), encoding="utf-8")


def test_scoped_archive_provider_filters_structured_query_and_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_bundle(
        tmp_path,
        raw_suffix="20260512120000",
        cl_name="hit",
        status="FAILED",
        project_file="/tmp/projects/sase/sase.sase",
    )
    _write_bundle(
        tmp_path,
        raw_suffix="20260512130000",
        cl_name="wrong_project",
        status="FAILED",
        project_file="/tmp/projects/other/other.sase",
    )
    rebuild_index(tmp_path)
    monkeypatch.setattr("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path)
    selection = SelectionItem("[P] sase", "project", "sase", None)
    provider = _ScopedArchiveQueryProvider(selection)

    page = provider.search("status:failed", limit=10)

    assert [row.cl_name for row in page.results] == ["hit"]
