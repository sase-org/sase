from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sase.agents.cli_search import handle_agents_search
from sase.project_display_names import ProjectRefDisplaySnapshot


def test_agent_search_archive_cli_matches_shared_corpus_order(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    from sase.ace import dismissed_agents
    from sase.ace.dismissed_bundle_index import DismissedBundleIndexProgress
    from sase.ace.query_profile.profiles._agents_archive import (
        agents_archive_query_schema,
    )
    from sase.ace.query_profile import compile_query_profile
    from sase.core.agent_archive_corpus_cache import (
        get_agent_archive_corpus,
        invalidate_agent_archive_corpus_cache,
    )
    from sase.project_display_names import ProjectDisplaySnapshot
    from tests._agent_archive_index_fixtures import insert_archive_rows

    insert_archive_rows(
        tmp_path,
        (
            {
                "run_id": "old",
                "name": "old",
                "status": "DONE",
                "stop_time": "2025-03-02T10:10:00Z",
            },
            {
                "run_id": "failed",
                "name": "failed",
                "status": "FAILED",
                "stop_time": "2025-03-02T10:20:00Z",
            },
            {
                "run_id": "clan-a",
                "name": "clan-a",
                "clan": "archive-clan",
                "clan_generation": "g1",
                "status": "DONE",
                "stop_time": "2025-03-02T10:30:00Z",
            },
            {
                "run_id": "clan-b",
                "name": "clan-b",
                "clan": "archive-clan",
                "clan_generation": "g1",
                "status": "RUNNING",
                "stop_time": "2025-03-02T10:40:00Z",
            },
            {"run_id": "child", "name": "workflow-child", "workflow_child": True},
        ),
    )
    monkeypatch.setattr(dismissed_agents, "_DISMISSED_BUNDLES_DIR", tmp_path)
    from sase.core import agent_archive_corpus_cache

    monkeypatch.setattr(
        agent_archive_corpus_cache, "_build_fallback_facets", lambda: {}
    )
    from sase.agents import cli_search

    display = ProjectRefDisplaySnapshot(
        display_snapshot=ProjectDisplaySnapshot({"sase": "sase"})
    )
    monkeypatch.setattr(
        cli_search, "load_project_ref_display_snapshot", lambda: display
    )
    invalidate_agent_archive_corpus_cache()
    cached = get_agent_archive_corpus(
        root=tmp_path,
        progress=DismissedBundleIndexProgress(rebuilding=False, indexed_rows=5),
        link_facets={},
        profile=compile_query_profile(agents_archive_query_schema()),
    )

    try:
        for query in ("", "outcome:failed", "project:sase", "clan:archive-clan"):
            summary = cached.corpus.summary(
                query, group_by="day", profile=cached.profile
            )
            expected = [
                row
                for group in summary["groups"]
                for row in cached.corpus.rows(
                    query,
                    group_by="day",
                    group_key=group["key"],
                    offset=0,
                    limit=group["count"],
                    profile=cached.profile,
                )["rows"]
            ]
            code = handle_agents_search(
                argparse.Namespace(
                    json=True,
                    limit=0,
                    project=None,
                    query=["in:archive", *query.split()],
                )
            )

            assert code == 0
            actual = json.loads(capsys.readouterr().out)

            def identity(row: dict[str, Any]) -> tuple[str, str, str]:
                key = row["archive_key"]
                return (
                    key["source_username"],
                    key["source_machine"],
                    key["source_run_id"],
                )

            assert [identity(row) for row in actual] == [
                identity(row) for row in expected
            ]
    finally:
        invalidate_agent_archive_corpus_cache()
