"""Tests for ``sase agent search``."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.query.profile_evaluator import coerce_artifact_query_rows_with_wire
from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.agents.catalog import AgentCatalogRow, AgentCatalogSnapshot
from sase.agents.catalog import agent_catalog_query_entry
from sase.agents.cli_search import handle_agents_search
from sase.main.parser import create_parser
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from tests._agent_catalog_helpers import make_agent_catalog_row
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
    "historically_viewable",
    "durably_revivable",
    "restartable",
    "missing_requirements",
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
    assert "linked:true AND relation:read" in search_help
    assert "Nm means months" in search_help
    assert "Nm means minutes" in search_help


def test_agent_search_parser_accepts_options_before_and_after_query() -> None:
    parser = create_parser(only="agent")
    before = parser.parse_args(
        ["agent", "search", "-j", "-l", "5", "-p", "sase", "kind:family"]
    )
    after = parser.parse_args(
        ["agent", "search", "kind:family", "-j", "-l", "5", "-p", "sase"]
    )
    interleaved = parser.parse_args(
        ["agent", "search", "kind:family", "-l", "5", "-p", "sase", "-j"]
    )

    for args in (before, after, interleaved):
        assert args.json is True
        assert args.limit == 5
        assert args.project == "sase"
        assert args.query == ["kind:family"]


def test_agent_search_boolean_dialect_has_no_leading_dash_spelling() -> None:
    """The boolean dialect negates with ``NOT``, never a leading ``-``, so
    ``nargs="*"`` swallowing a lone ``-foo`` token as an unrecognized option is
    expected: there is no real query a user would need ``--`` to escape."""
    parser = create_parser(only="agent")

    with pytest.raises(SystemExit):
        parser.parse_args(["agent", "search", "-foo"])


def test_agent_search_handles_options_parsed_after_the_query(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    snapshot = _snapshot(_row("visible", kind=("family",)))
    _patch_sources(monkeypatch, snapshot)
    parser = create_parser(only="agent")

    args = parser.parse_args(
        ["agent", "search", "kind:family", "-j", "-l", "5", "-p", "sase"]
    )
    code = handle_agents_search(args)

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in payload] == ["visible"]


def test_agent_search_query_followed_by_limit_flag_does_not_hit_tokenizer_error(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Regression test for a REMAINDER-nargs bug: ``-l 3`` after the query used to
    be swallowed into the query text and reach the tokenizer as literal characters."""
    snapshot = _snapshot(_row("visible", kind=("family",)))
    _patch_sources(monkeypatch, snapshot)
    parser = create_parser(only="agent")

    args = parser.parse_args(["agent", "search", "kind:family", "-l", "3"])
    code = handle_agents_search(args)

    assert code == 0
    output = capsys.readouterr().out
    assert "error" not in output.lower()
    assert "visible" in output


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


def test_agent_catalog_query_entry_emits_stable_rust_wire_shape() -> None:
    display = ProjectRefDisplaySnapshot(
        display_snapshot=ProjectDisplaySnapshot({"gh_sase-org__sase": "sase"})
    )
    started = "2026-08-01T00:00:00+00:00"
    finished = _epoch("2026-08-01T00:05:00+00:00")
    row = _row(
        "research.12--code",
        family="research.12",
        role="code",
        clan="athena.sase-tt",
        tribe="epic",
        workflow="review",
        parent_timestamp="20260801000100",
        raw_suffix="20260801000000",
        artifacts_dir="/agents/research.12--code",
        bundle_path="/dismissed/research.12--code.json",
        state="dismissed",
        status="running",
        hidden=True,
        dismissed=True,
        revivable=True,
        attention=True,
        retry=True,
        retry_attempt=2,
        started_at=started,
        finished_at=finished,
        patch="sase-tt",
    )

    entry = agent_catalog_query_entry(row, project_ref_display=display)
    profile = compiled_profile_for_builtin_pane("agents")
    assert profile is not None
    _rows, wire_rows = coerce_artifact_query_rows_with_wire(profile, (entry,))

    assert entry.stable_id == "agent:research.12--code"
    assert wire_rows == [
        {
            "fields": {
                "kind": ["agent"],
                "name": [
                    "research.12--code",
                    "bbugyi200.athena.research.12--code",
                ],
                "project": ["gh_sase-org__sase", "sase"],
                "state": ["dismissed"],
                "status": ["RUNNING"],
                "hidden": [True],
                "dismissed": [True],
                "revivable": [True],
                "historically_viewable": [False],
                "durably_revivable": [False],
                "restartable": [False],
                "attention": [True],
                "retry": [True],
                "linked": [False],
                "family": ["research.12"],
                "role": ["code"],
                "clan": ["athena.sase-tt"],
                "tribe": ["epic"],
                "workflow": ["review"],
                "parent": ["20260801000100"],
                "model": ["gpt-5"],
                "provider": ["codex"],
                "patch": ["sase-tt"],
                "attempt": [2],
                "since": [int(datetime.fromisoformat(started).timestamp())],
                "until": [int(datetime.fromisoformat(started).timestamp())],
                "after": [int(finished)],
                "before": [int(finished)],
                "min": [300],
                "max": [300],
                "label": [
                    "research.12--code",
                    "bbugyi200.athena.research.12--code",
                    "gh_sase-org__sase",
                    "sase",
                    "dismissed",
                    "RUNNING",
                    "gpt-5",
                    "codex",
                ],
                "text": [
                    "research.12--code",
                    "bbugyi200.athena.research.12--code",
                    "gh_sase-org__sase",
                    "sase",
                    "dismissed",
                    "RUNNING",
                    "gpt-5",
                    "codex",
                    "agent",
                    "research.12",
                    "code",
                    "athena.sase-tt",
                    "epic",
                    "review",
                    "20260801000100",
                    "20260801000000",
                    "/agents/research.12--code",
                    "/dismissed/research.12--code.json",
                    "sase-tt",
                ],
            },
            "searchable_text": "\n".join(str(item) for item in entry.fields["text"]),
            "predicates": {
                "error_suffix": False,
                "running_agent": True,
                "running_process": False,
            },
        }
    ]


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


def test_agent_search_filters_artifact_link_facets(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    snapshot = _snapshot(
        _row("alpha"),
        _row("beta"),
        _row("gamma"),
    )
    link_rows = (
        {
            "source_ref": "agent:alpha",
            "relation": "read",
            "target_ref": "plan:202608/example.md",
        },
        {
            "source_ref": "plan:202608/example.md",
            "relation": "implements",
            "target_ref": "agent:bbugyi200.athena.beta",
        },
    )
    _patch_sources(monkeypatch, snapshot, link_rows=link_rows)

    code = handle_agents_search(
        argparse.Namespace(
            json=True,
            limit=0,
            project=None,
            query=["relation:read", "AND", "linked:true"],
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in payload] == ["alpha"]

    code = handle_agents_search(
        argparse.Namespace(
            json=True,
            limit=0,
            project=None,
            query=["artifact:plan:202608/example.md"],
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {row["name"] for row in payload} == {"alpha", "beta"}

    for query, expected in (
        (["linked:true"], {"alpha", "beta"}),
        (["linked:false"], {"gamma"}),
    ):
        code = handle_agents_search(
            argparse.Namespace(json=True, limit=0, project=None, query=query)
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert {row["name"] for row in payload} == expected


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


def _patch_sources(
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


def _epoch(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()
