"""Imported family members fold under a synthesized family container."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sase.ace.tui.actions.agents._revive_helpers import is_child_of
from sase.ace.tui.models._agent_imported_family import (
    materialize_imported_family_containers,
)
from sase.ace.tui.models._agent_loader_normalization import normalize_loaded_agents
from sase.ace.tui.models._agent_tree import agent_is_tree_child, agent_tree_depth
from sase.ace.tui.models._loaders._meta_enrichment import enrich_agent_from_meta
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_bundle import from_bundle_dict, to_bundle_dict
from sase.core.agent_identity_facade import AgentOwnerIdentity


SOURCE = AgentOwnerIdentity("bob", "zeus")


def _imported_member(
    *,
    name: str,
    role: str,
    suffix: str,
    second: int,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 7, 24, 12, 0, second),
        stop_time=datetime(2026, 7, 24, 12, 1, second),
        raw_suffix=suffix,
        agent_name=name,
        agent_family="bob.zeus.crew",
        agent_family_role=role,
        imported_source_owner=SOURCE,
    )


def test_imported_family_renders_grouped_without_code_orphan_roots() -> None:
    plan = _imported_member(
        name="bob.zeus.crew--plan",
        role="plan",
        suffix="20260724120001",
        second=1,
    )
    code = _imported_member(
        name="bob.zeus.crew--code",
        role="code",
        suffix="20260724120002",
        second=2,
    )
    monitor = _imported_member(
        name="bob.zeus.crew--mon",
        role="monitor",
        suffix="20260724120003",
        second=3,
    )
    rows = normalize_loaded_agents(
        [code, monitor, plan],
        [],
        is_process_running=lambda _pid: False,
    )

    roots = [row for row in rows if not agent_is_tree_child(row)]
    assert len(roots) == 1
    container = roots[0]
    assert container.is_imported_family_container
    assert container.is_family_root_entry
    assert container.agent_family == "bob.zeus.crew"
    members = [row for row in rows if row is not container]
    assert {row.agent_family_role for row in members} == {"plan", "code", "monitor"}
    assert all(row.is_family_member_child for row in members)
    assert all(agent_tree_depth(row) > 0 for row in members)
    assert all(row.parent_timestamp == container.raw_suffix for row in members)
    assert "--code" not in {row.agent_name for row in roots}


def test_reviving_imported_family_restores_root_and_members() -> None:
    plan = _imported_member(
        name="bob.zeus.crew--plan",
        role="plan",
        suffix="20260724120001",
        second=1,
    )
    code = _imported_member(
        name="bob.zeus.crew--code",
        role="code",
        suffix="20260724120002",
        second=2,
    )
    monitor = _imported_member(
        name="bob.zeus.crew--mon",
        role="monitor",
        suffix="20260724120003",
        second=3,
    )
    rows = materialize_imported_family_containers([plan, code, monitor])
    container = next(row for row in rows if row.is_imported_family_container)
    members = [row for row in rows if row is not container]
    visible = [row for row in rows if not row.is_workflow_child]

    assert visible == [container]
    assert all(is_child_of(member, container) for member in members)
    assert {member.agent_family_role for member in members} == {
        "plan",
        "code",
        "monitor",
    }


def test_imported_source_owner_loads_from_meta_and_bundle(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "bob.zeus.crew--code",
                "agent_family": "bob.zeus.crew",
                "agent_family_role": "code",
                "imported_source_owner": {
                    "username": "bob",
                    "machine_name": "zeus",
                },
            }
        ),
        encoding="utf-8",
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 7, 24, 12, 0, 0),
        raw_suffix="20260724120002",
    )
    enrich_agent_from_meta(agent, str(tmp_path))
    assert agent.imported_source_owner == SOURCE
    assert agent.agent_family == "bob.zeus.crew"

    bundle = to_bundle_dict(agent)
    assert bundle["imported_source_owner"] == {
        "username": "bob",
        "machine_name": "zeus",
    }
    json.dumps(bundle)
    loaded = from_bundle_dict(bundle)
    assert loaded.imported_source_owner == SOURCE


def test_synthetic_imported_family_parent_is_not_persisted() -> None:
    code = _imported_member(
        name="bob.zeus.crew--code",
        role="code",
        suffix="20260724120002",
        second=2,
    )
    rows = materialize_imported_family_containers([code])
    member = next(row for row in rows if not row.is_imported_family_container)
    assert member.parent_timestamp is not None
    bundle = to_bundle_dict(member)
    assert bundle.get("parent_timestamp") is None
    assert "is_imported_family_container" not in bundle
