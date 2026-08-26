"""Coverage tests for the `agent-bead` projection rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.artifact_links.projection._agent_bead import project_agent_bead_rows
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


def test_emits_one_row_per_bead_field(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(
        root,
        "alice.athena.9w",
        _meta(metadata={"bead_id": "sase-xx", "epic_bead_id": "sase-yy"}),
    )

    edges = project_agent_bead_rows(_inputs(root))

    assert {(edge.relation, edge.target_ref) for edge in edges} == {
        ("implements", "bead:sase-xx"),
        ("implements", "bead:sase-yy"),
    }
    assert all(edge.source_ref == "agent:alice.athena.9w" for edge in edges)
    assert all(edge.rule_id == "agent-bead" for edge in edges)
    assert all(edge.description for edge in edges)


def test_three_bead_fields_stay_distinguishable_by_description(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(
        root,
        "alice.athena.9w",
        _meta(
            metadata={
                "bead_id": "sase-aa",
                "epic_bead_id": "sase-bb",
                "phase_bead_id": "sase-cc",
            }
        ),
    )

    edges = project_agent_bead_rows(_inputs(root))

    descriptions = {edge.description for edge in edges}
    assert len(descriptions) == 3
    assert any("bead_id" in text and "epic" not in text for text in descriptions)
    assert any("epic_bead_id" in text for text in descriptions)
    assert any("phase_bead_id" in text for text in descriptions)


def test_skips_agent_with_no_bead_fields(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(root, "alice.athena.9w", _meta())

    assert project_agent_bead_rows(_inputs(root)) == ()


def test_skips_a_blank_bead_field(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(root, "alice.athena.9w", _meta(metadata={"bead_id": "   "}))

    assert project_agent_bead_rows(_inputs(root)) == ()


def test_no_agents_root_is_a_no_op() -> None:
    assert project_agent_bead_rows(_inputs(None)) == ()


def test_no_agents_directory_under_the_root_is_a_no_op(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    root.mkdir()

    assert project_agent_bead_rows(_inputs(root)) == ()


def test_unparseable_meta_json_contributes_no_row(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    page_dir = root / "agents" / "alice.athena.9w"
    page_dir.mkdir(parents=True)
    (page_dir / "meta.json").write_text("not json", encoding="utf-8")

    assert project_agent_bead_rows(_inputs(root)) == ()


def test_warm_run_is_idempotent_when_nothing_changed(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(root, "alice.athena.9w", _meta(metadata={"bead_id": "sase-xx"}))

    first = project_agent_bead_rows(_inputs(root))
    second = project_agent_bead_rows(_inputs(root))

    assert first == second


def test_stale_agent_disappears_after_it_is_removed_from_disk(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(root, "alice.athena.9w", _meta(metadata={"bead_id": "sase-xx"}))
    project_agent_bead_rows(_inputs(root))

    import shutil

    shutil.rmtree(root / "agents" / "alice.athena.9w")

    assert project_agent_bead_rows(_inputs(root)) == ()


def test_only_the_changed_agent_is_reparsed(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    _write_agent(root, "alice.athena.9w", _meta(metadata={"bead_id": "sase-xx"}))
    _write_agent(
        root,
        "alice.athena.10z",
        _meta(
            local_name="10z",
            global_name="alice.athena.10z",
            metadata={"bead_id": "sase-yy"},
        ),
    )
    first = project_agent_bead_rows(_inputs(root))
    assert len(first) == 2

    # Rewrite only the second agent's meta.json with a new, differently-sized
    # bead id -- the cache key is (mtime_ns, size), and a same-size rewrite
    # within one filesystem timer tick can leave mtime_ns unchanged too.
    _write_agent(
        root,
        "alice.athena.10z",
        _meta(
            local_name="10z",
            global_name="alice.athena.10z",
            metadata={"bead_id": "sase-zzzzzz"},
        ),
    )
    second = project_agent_bead_rows(_inputs(root))

    targets = {edge.target_ref for edge in second}
    assert targets == {"bead:sase-xx", "bead:sase-zzzzzz"}
