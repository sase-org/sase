"""Agents-list projection keeps loader parity without decoding marker-only rows."""

from __future__ import annotations

import os
from pathlib import Path

from sase.ace.tui.models.agent_loader import load_tiered_agents
from sase.core.agent_scan_facade import query_agent_artifact_index
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
)
from sase.running_field import WorkspaceClaim

from tests.perf._agent_load_tiering_rows import _temporary_sase_home
from tests.perf.agent_load_tiering_fixture import (
    build_synthetic_agent_archive,
    rebuild_index,
    write_completed_artifact,
    write_waiting_artifact,
)
from tests.perf.agent_load_tiering_harness import AgentLoadTieringOracle


def _projection_query(*, full_history: bool = False) -> AgentArtifactIndexQueryWire:
    if full_history:
        return AgentArtifactIndexQueryWire(
            include_active=False,
            include_recent_completed=False,
            include_full_history=True,
            include_hidden=False,
            freshness="cached",
            record_shape="list",
            agents_list_projection=True,
        )
    return AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=False,
        include_hidden=False,
        freshness="cached",
        record_shape="list",
        window_limit=50,
        agents_list_projection=True,
    )


def test_generic_index_query_still_returns_waiting_only_records(tmp_path: Path) -> None:
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=24)
    waiting = write_waiting_artifact(fixture.projects_root, fixture.artifact_count + 1)
    rebuild_index(fixture)

    snapshot = query_agent_artifact_index(
        fixture.index_path,
        fixture.projects_root,
        AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=False,
            freshness="cached",
            record_shape="list",
        ),
        AgentArtifactScanOptionsWire(),
    )
    assert any(record.artifact_dir == str(waiting) for record in snapshot.records)


def test_projection_query_omits_waiting_only_and_keeps_done_rows(
    tmp_path: Path,
) -> None:
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=24)
    waiting = write_waiting_artifact(fixture.projects_root, fixture.artifact_count + 1)
    done = write_completed_artifact(fixture.projects_root, fixture.artifact_count + 2)
    rebuild_index(fixture)

    snapshot = query_agent_artifact_index(
        fixture.index_path,
        fixture.projects_root,
        _projection_query(),
        AgentArtifactScanOptionsWire(),
    )
    dirs = {record.artifact_dir for record in snapshot.records}
    assert str(waiting) not in dirs
    assert str(done) in dirs
    assert snapshot.stats.record_json_decoded == len(snapshot.records)


def test_production_paths_keep_parity_with_marker_only_population(
    tmp_path: Path,
) -> None:
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=72)
    write_waiting_artifact(fixture.projects_root, fixture.artifact_count + 1)
    write_completed_artifact(
        fixture.projects_root,
        fixture.artifact_count + 2,
        outcome="noop",
    )
    rebuild_index(fixture)
    oracle = AgentLoadTieringOracle(fixture)
    result = oracle.evaluate("", requested_limit=400)

    for name in ("production_bounded", "production_full_history"):
        diff = result.diff_for(name)
        assert diff.missing == (), name
        assert diff.visible_extra == (), name


def test_running_claim_gets_clan_context_from_waiting_only_scalars(
    tmp_path: Path,
) -> None:
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=24)
    waiting = write_waiting_artifact(
        fixture.projects_root,
        fixture.artifact_count + 1,
        agent_clan="claim-clan",
        agent_clan_generation="g1",
        clan_tribe="chop",
        clan_summary="Waiting supplies context",
    )
    spec = fixture.projects_root / "gh_sase-org__sase" / "gh_sase-org__sase.sase"
    claim = WorkspaceClaim(
        workspace_num=7,
        workflow="ace-run",
        cl_name="claim-clan-run",
        pid=os.getpid(),
        artifacts_timestamp=waiting.name,
    )
    spec.write_text(
        spec.read_text(encoding="utf-8") + "\nRUNNING:\n" + claim.to_line() + "\n",
        encoding="utf-8",
    )
    rebuild_index(fixture)

    snapshot = query_agent_artifact_index(
        fixture.index_path,
        fixture.projects_root,
        _projection_query(full_history=True),
        AgentArtifactScanOptionsWire(),
    )
    assert all(record.artifact_dir != str(waiting) for record in snapshot.records)
    context = next(
        item
        for item in snapshot.clan_context
        if item.agent_clan == "claim-clan" and item.agent_clan_generation == "g1"
    )
    assert context.clan_tribe == "chop"
    assert context.clan_summary == "Waiting supplies context"

    with _temporary_sase_home(fixture.sase_home):
        agents, state = load_tiered_agents(full_history=True)
    claimed = next(agent for agent in agents if agent.cl_name == "claim-clan-run")
    assert claimed.agent_clan == "claim-clan"
    assert claimed.clan_context is not None
    assert claimed.clan_context.clan_tribe == "chop"
    assert claimed.clan_context.clan_summary == "Waiting supplies context"
    assert state.record_json_decoded is not None
