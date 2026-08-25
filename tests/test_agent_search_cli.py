"""Tests for ``sase agent search``."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from typing import Any

from sase.agents.catalog import AgentCatalogRow, AgentCatalogSnapshot
from sase.agents.cli_search import handle_agents_search
from sase.main.parser import create_parser
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from tests.main.parser_help_helpers import help_subcommand_rows, parser_for

_JSON_KEYS = {
    "name",
    "canonical_global_name",
    "kind",
    "project",
    "project_display",
    "state",
    "status",
    "hidden",
    "dismissed",
    "revivable",
    "attention",
    "retry",
    "attempt",
    "family",
    "role",
    "clan",
    "tribe",
    "workflow",
    "parent",
    "model",
    "provider",
    "patch",
    "started_at",
    "finished_at",
    "runtime_seconds",
    "raw_suffix",
    "artifacts_dir",
    "bundle_path",
    "from_artifact_index",
    "from_dismissed_archive",
    "has_collision_history",
}


def test_agent_search_parser_and_help_are_complete_and_sorted() -> None:
    parser = create_parser(only="agent")
    args = parser.parse_args(
        [
            "agent",
            "search",
            "-j",
            "-l",
            "5",
            "-p",
            "sase",
            "revivable:true",
            "AND",
            "role:code",
        ]
    )

    assert args.agent_subcommand == "search"
    assert args.json is True
    assert args.limit == 5
    assert args.project == "sase"
    assert args.query == ["revivable:true", "AND", "role:code"]

    expected_commands = {
        "archive",
        "artifacts",
        "drain",
        "index",
        "kill",
        "list",
        "names",
        "persist-cleanup",
        "persist-directive",
        "prompts",
        "restart",
        "retire-v1",
        "revert",
        "search",
        "show",
        "sync",
        "tribe",
        "wait",
    }
    agent_help = parser_for(("sase", "agent")).format_help()
    assert help_subcommand_rows(agent_help, expected_commands) == sorted(
        expected_commands
    )

    search_help = parser_for(("sase", "agent", "search")).format_help()
    assert "-j" in search_help
    assert "--json" in search_help
    assert "-l LIMIT" in search_help
    assert "--limit LIMIT" in search_help
    assert "-p PROJECT" in search_help
    assert "--project PROJECT" in search_help
    assert "revivable:true AND project:sase AND role:code" in search_help
    assert "Nm means months" in search_help
    assert "Nm means minutes" in search_help


def test_agent_search_json_filters_with_shared_profile(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    snapshot = _snapshot(
        _row(
            "research.12--code",
            role="code",
            family="research.12",
            state="dismissed",
            status="failed",
            revivable=True,
            dismissed=True,
            bundle_path="/dismissed/research.12.json",
            started_at="2026-08-01T00:00:00+00:00",
            finished_at=_epoch("2026-08-01T00:05:00+00:00"),
        ),
        _row("other", project="other", role="code", state="dismissed", revivable=True),
    )
    _patch_sources(monkeypatch, snapshot)

    code = handle_agents_search(
        argparse.Namespace(
            json=True,
            limit=None,
            project="sase",
            query=["revivable:true", "AND", "role:code", "AND", "min:5m"],
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    row = payload[0]
    assert set(row) == _JSON_KEYS
    assert row["name"] == "research.12--code"
    assert row["project"] == "gh_sase-org__sase"
    assert row["project_display"] == "sase"
    assert row["status"] == "FAILED"
    assert row["runtime_seconds"] == 300


def test_agent_search_default_scope_excludes_hidden_and_workflow_children(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    snapshot = _snapshot(
        _row("visible"),
        _row("hidden", hidden=True),
        _row("child", kind=("member", "workflow-child"), family="fam"),
    )
    _patch_sources(monkeypatch, snapshot)

    code = handle_agents_search(
        argparse.Namespace(json=True, limit=0, project=None, query=[])
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in payload] == ["visible"]


def test_agent_search_pretty_output_smoke(monkeypatch: Any, capsys: Any) -> None:
    snapshot = _snapshot(_row("visible", status="RUNNING", model="gpt-5"))
    _patch_sources(monkeypatch, snapshot)

    code = handle_agents_search(
        argparse.Namespace(json=False, limit=10, project=None, query=["status:RUNNING"])
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "Agent Catalog Search" in output
    assert "visible" in output
    assert "RUNNING" in output


def _patch_sources(monkeypatch: Any, snapshot: AgentCatalogSnapshot) -> None:
    from sase.agents import cli_search

    display = ProjectRefDisplaySnapshot(
        display_snapshot=ProjectDisplaySnapshot({"gh_sase-org__sase": "sase"}),
        aliases={"sase": "gh_sase-org__sase"},
    )
    monkeypatch.setattr(cli_search, "build_agent_catalog_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        cli_search, "load_project_ref_display_snapshot", lambda: display
    )


def _snapshot(*rows: AgentCatalogRow) -> AgentCatalogSnapshot:
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
    )


def _row(name: str, **overrides: Any) -> AgentCatalogRow:
    values: dict[str, Any] = {
        "name": name,
        "canonical_global_name": f"bbugyi200.athena.{name}",
        "kind": ("agent",),
        "project": "gh_sase-org__sase",
        "state": "active",
        "family": None,
        "role": None,
        "clan": None,
        "tribe": None,
        "workflow": None,
        "parent_timestamp": None,
        "retry_of_timestamp": None,
        "retried_as_timestamp": None,
        "retry_chain_root_timestamp": None,
        "raw_suffix": "20260801000000",
        "artifacts_dir": f"/artifacts/{name}",
        "bundle_path": None,
        "model": "gpt-5",
        "llm_provider": "codex",
        "status": "DONE",
        "hidden": False,
        "started_at": "2026-08-01T00:00:00+00:00",
        "finished_at": None,
        "retry_attempt": None,
        "patch": None,
        "dismissed": False,
        "revivable": False,
        "attention": False,
        "retry": False,
        "has_collision_history": False,
        "from_artifact_index": True,
        "from_dismissed_archive": False,
    }
    values.update(overrides)
    return AgentCatalogRow(**values)


def _epoch(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()
