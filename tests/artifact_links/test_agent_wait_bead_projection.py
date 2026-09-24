"""Coverage tests for the `agent-wait-bead` projection rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.artifact_links.projection._agent_wait_bead import (
    project_agent_wait_bead_rows,
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


def _inputs(root: Path | None) -> ProjectionInputs:
    return ProjectionInputs(
        project_key="gh_sase-org__sase",
        primary_repo_root=None,
        primary_repo_name=None,
        agents_sidecar_root=root,
    )


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")


def test_emits_one_row_per_distinct_bead_id(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(
        root,
        "alice.athena.9w",
        _meta(metadata={"wait_for_beads": ["sase-xx", "sase-yy"]}),
    )

    edges = project_agent_wait_bead_rows(_inputs(root))

    assert {(edge.relation, edge.target_ref) for edge in edges} == {
        ("awaits", "bead:sase-xx"),
        ("awaits", "bead:sase-yy"),
    }
    assert all(edge.source_ref == "agent:alice.athena.9w" for edge in edges)
    assert all(edge.rule_id == "agent-wait-bead" for edge in edges)
    assert all(edge.description for edge in edges)


def test_deduplicates_repeated_bead_ids(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(
        root,
        "alice.athena.9w",
        _meta(metadata={"wait_for_beads": ["sase-xx", "sase-xx", "sase-yy"]}),
    )

    edges = project_agent_wait_bead_rows(_inputs(root))

    assert [edge.target_ref for edge in edges] == ["bead:sase-xx", "bead:sase-yy"]


def test_skips_agent_with_no_wait_key(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(root, "alice.athena.9w", _meta())

    assert project_agent_wait_bead_rows(_inputs(root)) == ()


def test_ignores_empty_whitespace_and_non_string_entries(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(
        root,
        "alice.athena.9w",
        _meta(
            metadata={"wait_for_beads": ["", "   ", "sase-ok", 7, None, "has space"]}
        ),
    )

    edges = project_agent_wait_bead_rows(_inputs(root))

    assert [edge.target_ref for edge in edges] == ["bead:sase-ok"]


def test_non_list_wait_value_yields_no_rows(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(root, "alice.athena.9w", _meta(metadata={"wait_for_beads": "sase-xx"}))

    assert project_agent_wait_bead_rows(_inputs(root)) == ()


def test_no_agents_root_is_a_no_op() -> None:
    assert project_agent_wait_bead_rows(_inputs(None)) == ()


def test_no_agents_directory_under_the_root_is_a_no_op(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    root.mkdir()

    assert project_agent_wait_bead_rows(_inputs(root)) == ()


def test_unparseable_meta_json_contributes_no_row(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    page_dir = root / "agents" / "alice.athena.9w"
    page_dir.mkdir(parents=True)
    (page_dir / "meta.json").write_text("not json", encoding="utf-8")

    assert project_agent_wait_bead_rows(_inputs(root)) == ()


def test_warm_run_is_idempotent_when_nothing_changed(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(
        root, "alice.athena.9w", _meta(metadata={"wait_for_beads": ["sase-xx"]})
    )

    first = project_agent_wait_bead_rows(_inputs(root))
    second = project_agent_wait_bead_rows(_inputs(root))

    assert first == second


def test_changed_meta_json_recomputes(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(
        root, "alice.athena.9w", _meta(metadata={"wait_for_beads": ["sase-xx"]})
    )
    assert len(project_agent_wait_bead_rows(_inputs(root))) == 1

    _write_agent(
        root, "alice.athena.9w", _meta(metadata={"wait_for_beads": ["sase-yyyy"]})
    )
    second = project_agent_wait_bead_rows(_inputs(root))

    assert {edge.target_ref for edge in second} == {"bead:sase-yyyy"}
