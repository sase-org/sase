"""Aggregator-level and isolation tests for the projection layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.artifact_links.projection import build_projection_inputs, project_link_rows
from sase.artifact_links.projection._model import ProjectedEdge, ProjectionInputs
from sase.sdd._artifact_link_store_support import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from tests._conftest_environment import redirect_sase_home


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")


def test_a_store_with_no_repo_inventory_and_no_agents_root_projects_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("chop-agent must not read AXE config when inert")

    monkeypatch.setattr("sase.axe.config.load_axe_config", _boom)

    inputs = build_projection_inputs(
        project_key="does-not-exist-anywhere", sdd_store=None
    )

    assert inputs.primary_repo_root is None
    assert inputs.agents_sidecar_root is None
    assert project_link_rows(inputs) == ()


def test_every_row_is_materialized_with_the_projected_shape(tmp_path: Path) -> None:
    root = tmp_path / "agents-sidecar"
    page_dir = root / "agents" / "alice.athena.9w"
    page_dir.mkdir(parents=True)
    (page_dir / "meta.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "owner": {"username": "alice", "machine_name": "athena"},
                "project": {"key": "gh_sase-org__sase", "name": "sase"},
                "source_run_id": "abc123",
                "local_name": "9w",
                "global_name": "alice.athena.9w",
                "metadata": {"bead_id": "sase-xx"},
            }
        ),
        encoding="utf-8",
    )
    inputs = ProjectionInputs(
        project_key="gh_sase-org__sase",
        primary_repo_root=None,
        primary_repo_name=None,
        agents_sidecar_root=root,
    )

    rows = project_link_rows(inputs)

    assert len(rows) == 1
    row = rows[0]
    assert row["schema_version"] == ARTIFACT_LINK_ROW_SCHEMA_VERSION
    assert row["origin"] == "projected"
    assert row["created_by"] == "projection:agent-bead"
    assert row["uses"] == 1
    assert row["source_ref"] == "agent:alice.athena.9w"
    assert row["relation"] == "implements"
    assert row["target_ref"] == "bead:sase-xx"
    assert len(row["description"]) <= 240


def test_agent_with_bead_id_and_wait_for_beads_yields_both_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agents-sidecar"
    page_dir = root / "agents" / "alice.athena.9w"
    page_dir.mkdir(parents=True)
    (page_dir / "meta.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "owner": {"username": "alice", "machine_name": "athena"},
                "project": {"key": "gh_sase-org__sase", "name": "sase"},
                "source_run_id": "abc123",
                "local_name": "9w",
                "global_name": "alice.athena.9w",
                "metadata": {
                    "bead_id": "sase-xx",
                    "wait_for_beads": ["sase-yy"],
                },
            }
        ),
        encoding="utf-8",
    )
    inputs = ProjectionInputs(
        project_key="gh_sase-org__sase",
        primary_repo_root=None,
        primary_repo_name=None,
        agents_sidecar_root=root,
    )

    rows = project_link_rows(inputs)

    assert {(row["relation"], row["target_ref"]) for row in rows} == {
        ("implements", "bead:sase-xx"),
        ("awaits", "bead:sase-yy"),
    }


def test_project_link_rows_drops_edges_with_invalid_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One malformed edge from any rule must not reach the aggregate."""

    from sase.artifact_links.projection import _entry

    good = ProjectedEdge(
        source_ref="stitch:sase@0123456789abcdef0123456789abcdef01234567",
        relation="implements",
        target_ref="bead:sase-xx",
        description="commit trailer names bead sase-xx",
        rule_id="stitch-bead",
        created_at="2026-08-20T00:00:00Z",
    )
    bad = ProjectedEdge(
        source_ref="stitch:sase@fedcba9876543210fedcba9876543210fedcba98",
        relation="implements",
        target_ref="bead:[sase-xx]",
        description="commit trailer names bead [sase-xx]",
        rule_id="stitch-bead",
        created_at="2026-08-20T00:00:00Z",
    )
    monkeypatch.setattr(_entry, "project_stitch_rules", lambda _inputs: (good, bad))
    monkeypatch.setattr(_entry, "project_agent_bead_rows", lambda _inputs: ())
    # `_agent_created_epic` rules are imported lazily inside
    # `project_link_rows` to keep the TUI startup closure lean, so they are
    # patched at their defining module.
    from sase.artifact_links.projection import _agent_created_epic

    monkeypatch.setattr(
        _agent_created_epic, "project_agent_created_epic_rows", lambda _inputs: ()
    )
    monkeypatch.setattr(
        _agent_created_epic,
        "project_agent_created_epic_attributed_rows",
        lambda _inputs: (),
    )
    monkeypatch.setattr(_entry, "project_agent_wait_bead_rows", lambda _inputs: ())
    monkeypatch.setattr(_entry, "project_chop_agent_rows", lambda _inputs: ())
    inputs = ProjectionInputs(
        project_key="gh_sase-org__sase",
        primary_repo_root=None,
        primary_repo_name=None,
        agents_sidecar_root=None,
    )

    rows = project_link_rows(inputs)

    assert [row["target_ref"] for row in rows] == ["bead:sase-xx"]
