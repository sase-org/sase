"""Coverage tests for the `agent-created-epic` projection rules."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.artifact_links.projection import project_link_rows
from sase.artifact_links.projection._agent_created_epic import (
    project_agent_created_epic_attributed_rows,
    project_agent_created_epic_rows,
)
from sase.artifact_links.projection._model import ProjectionInputs
from tests._conftest_environment import redirect_sase_home

_OWNER = {"username": "alice", "machine_name": "athena"}
_PROJECT = {"key": "gh_sase-org__sase", "name": "sase"}


def _meta(
    *,
    local_name: str = "9w",
    global_name: str = "alice.athena.9w",
    metadata: dict | None = None,
) -> dict:
    return {
        "schema_version": 2,
        "owner": _OWNER,
        "project": _PROJECT,
        "source_run_id": "abc123",
        "local_name": local_name,
        "global_name": global_name,
        "metadata": metadata or {},
    }


def _write_agent(root: Path, global_name: str, meta: dict) -> None:
    page_dir = root / "agents" / global_name
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _inputs(root: Path | None, bead_store_root: Path | None = None) -> ProjectionInputs:
    return ProjectionInputs(
        project_key="gh_sase-org__sase",
        primary_repo_root=None,
        primary_repo_name=None,
        agents_sidecar_root=root,
        bead_store_root=bead_store_root,
    )


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")


def test_published_epic_ids_project_produced_by(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(
        root,
        "alice.athena.9w",
        _meta(metadata={"created_epic_ids": ["sase-7k", "sase-7m"]}),
    )

    edges = project_agent_created_epic_rows(_inputs(root))

    assert {(edge.relation, edge.source_ref, edge.target_ref) for edge in edges} == {
        ("produced-by", "bead:sase-7k", "agent:alice.athena.9w"),
        ("produced-by", "bead:sase-7m", "agent:alice.athena.9w"),
    }
    assert all(edge.rule_id == "agent-created-epic" for edge in edges)
    assert all(edge.description for edge in edges)


def test_published_epic_ids_dedup_and_skip_bad_entries(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(
        root,
        "alice.athena.9w",
        _meta(
            metadata={
                "created_epic_ids": ["sase-7k", "sase-7k", "", "  ", 7, None, "a b"]
            }
        ),
    )

    edges = project_agent_created_epic_rows(_inputs(root))

    assert [edge.source_ref for edge in edges] == ["bead:sase-7k"]


def test_meta_without_created_epic_ids_projects_nothing(tmp_path: Path) -> None:
    """An older publisher's metadata leaves the new rule silent."""

    root = tmp_path / "agents-sidecar"
    _write_agent(root, "alice.athena.9w", _meta(metadata={"epic_bead_id": "sase-7k"}))

    assert project_agent_created_epic_rows(_inputs(root)) == ()


def test_worker_gets_no_produced_by_for_inherited_epic(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(
        root,
        "alice.athena.worker",
        _meta(
            local_name="worker",
            global_name="alice.athena.worker",
            metadata={
                "epic_bead_id": "sase-7p",
                "phase_bead_id": "sase-7p.1",
                "created_epic_ids": ["sase-7k"],
            },
        ),
    )

    rows = project_link_rows(_inputs(root))

    assert {
        (row["relation"], row["source_ref"], row["target_ref"]) for row in rows
    } == {
        ("implements", "agent:alice.athena.worker", "bead:sase-7p"),
        ("implements", "agent:alice.athena.worker", "bead:sase-7p.1"),
        ("produced-by", "bead:sase-7k", "agent:alice.athena.worker"),
    }


def _issue(bead_id: str, *, created_by: object = "") -> SimpleNamespace:
    return SimpleNamespace(id=bead_id, created_by=created_by)


def _attributed_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, issues: list
) -> ProjectionInputs:
    import sase.artifact_links.projection._agent_created_epic as module

    monkeypatch.setattr(module, "_epic_plan_issues", lambda _root: issues)
    store = tmp_path / "beads"
    store.mkdir(exist_ok=True)
    return _inputs(None, bead_store_root=store)


def test_attributed_rule_covers_unpublished_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _attributed_inputs(
        tmp_path,
        monkeypatch,
        [_issue("sase-7k", created_by="bbugyi200.athena.planner")],
    )

    edges = project_agent_created_epic_attributed_rows(inputs)

    assert [(edge.relation, edge.source_ref, edge.target_ref) for edge in edges] == [
        ("produced-by", "bead:sase-7k", "agent:bbugyi200.athena.planner")
    ]
    assert all(edge.rule_id == "agent-created-epic-attributed" for edge in edges)


def test_attributed_rule_skips_human_and_blank_creators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _attributed_inputs(
        tmp_path,
        monkeypatch,
        [
            _issue("sase-7a", created_by="owner@example.com"),
            _issue("sase-7b", created_by="bryan"),
            _issue("sase-7c", created_by=""),
            _issue("sase-7d", created_by="has space.x"),
            _issue("sase-7e", created_by=None),
        ],
    )

    assert project_agent_created_epic_attributed_rows(inputs) == ()


def test_attributed_rule_without_store_root_is_a_no_op() -> None:
    assert project_agent_created_epic_attributed_rows(_inputs(None)) == ()


def test_attributed_rule_with_unreadable_store_is_a_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.artifact_links.projection._agent_created_epic as module

    def _boom(_root: Path) -> list:
        raise RuntimeError("store gone")

    monkeypatch.setattr(module, "_epic_plan_issues", _boom)
    store = tmp_path / "beads"
    store.mkdir(exist_ok=True)

    assert (
        project_agent_created_epic_attributed_rows(_inputs(None, bead_store_root=store))
        == ()
    )
