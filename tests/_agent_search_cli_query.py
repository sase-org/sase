from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from typing import Any

from sase.ace.query.profile_evaluator import coerce_artifact_query_rows_with_wire
from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.agents.catalog import agent_catalog_query_entry
from sase.agents.cli_search import handle_agents_search
from sase.project_display_names import ProjectDisplaySnapshot, ProjectRefDisplaySnapshot
from tests._agent_search_cli_helpers import (
    epoch,
    patch_sources,
    make_row,
    make_snapshot,
)

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
    "agent_session",
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


def test_agent_search_json_filters_with_shared_profile(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    snapshot = make_snapshot(
        make_row(
            "research.12--code",
            role="code",
            agent_session="research.12",
            state="dismissed",
            status="failed",
            revivable=True,
            dismissed=True,
            bundle_path="/dismissed/research.12.json",
            started_at="2026-08-01T00:00:00+00:00",
            finished_at=epoch("2026-08-01T00:05:00+00:00"),
        ),
        make_row(
            "other", project="other", role="code", state="dismissed", revivable=True
        ),
    )
    patch_sources(monkeypatch, snapshot)

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
    finished = epoch("2026-08-01T00:05:00+00:00")
    row = make_row(
        "research.12--code",
        agent_session="research.12",
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
                "session": ["research.12"],
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
    snapshot = make_snapshot(
        make_row("visible"),
        make_row("hidden", hidden=True),
        make_row("child", kind=("member", "workflow-child"), agent_session="fam"),
    )
    patch_sources(monkeypatch, snapshot)

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
    snapshot = make_snapshot(
        make_row("alpha"),
        make_row("beta"),
        make_row("gamma"),
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
    patch_sources(monkeypatch, snapshot, link_rows=link_rows)

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


def test_agent_search_inbox_scope_restricts_catalog_to_non_dismissed_rows(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    snapshot = make_snapshot(
        make_row("visible"),
        make_row("dismissed", dismissed=True, state="dismissed"),
        make_row("hidden", hidden=True),
    )
    patch_sources(monkeypatch, snapshot)

    code = handle_agents_search(
        argparse.Namespace(json=True, limit=0, project=None, query=["in:inbox"])
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in payload] == ["visible"]


def test_agent_search_scope_hints_name_the_other_profile_field(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    patch_sources(monkeypatch, make_snapshot(make_row("visible")))

    code = handle_agents_search(
        argparse.Namespace(
            json=True,
            limit=0,
            project=None,
            query=["in:archive", "unread:true"],
        )
    )

    assert code == 2
    assert "unread: is an Inbox field" in capsys.readouterr().err


def test_agent_search_rejects_invalid_in_token(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    snapshot = make_snapshot(make_row("visible"))
    patch_sources(monkeypatch, snapshot)

    code = handle_agents_search(
        argparse.Namespace(json=True, limit=0, project=None, query=["in:history"])
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "in:" in err
    assert "inbox" in err or "archive" in err


def test_agent_search_session_field_and_kind_match_session_rows(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    snapshot = make_snapshot(
        make_row("research.12--code", agent_session="research.12", kind=("session",)),
        make_row("solo"),
    )
    patch_sources(monkeypatch, snapshot)

    for query in (
        ["session:research.12"],
        ["kind:session"],
        ['session:"research.12"'],
    ):
        code = handle_agents_search(
            argparse.Namespace(json=True, limit=0, project=None, query=query)
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert [row["name"] for row in payload] == ["research.12--code"]
        assert payload[0]["agent_session"] == "research.12"
        assert "family" not in payload[0]


def test_agent_search_legacy_family_terms_are_accepted_aliases(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    snapshot = make_snapshot(
        make_row("research.12--code", agent_session="research.12", kind=("session",)),
        make_row("solo"),
    )
    patch_sources(monkeypatch, snapshot)

    # legacy agent-family spelling: the old query terms still resolve
    for query in (["family:research.12"], ["kind:family"]):
        code = handle_agents_search(
            argparse.Namespace(json=True, limit=0, project=None, query=query)
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert [row["name"] for row in payload] == ["research.12--code"]
