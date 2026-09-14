"""Tests for linked-repo, plan-reference, and source-machine metadata enrichment."""

import json
from pathlib import Path

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import LinkedRepoMetadata
from sase.core.agent_scan_wire import AgentMetaWire
from tests._enrich_agent_helpers import make_agent


def test_linked_repos_from_agent_meta(tmp_path: Path) -> None:
    """linked_repos are parsed from agent_meta.json during enrichment."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "linked_repos": [
                    {
                        "name": "sase-core",
                        "workspace_dir": "/tmp/sase-core_7",
                        "workspace_strategy": "suffix",
                    },
                    {
                        "name": "missing-workspace",
                        "workspace_strategy": "suffix",
                    },
                    "invalid",
                ],
            }
        )
    )

    agent = make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.linked_repos == (
        LinkedRepoMetadata(
            name="sase-core",
            workspace_dir="/tmp/sase-core_7",
        ),
    )


def test_linked_repos_from_agent_meta_wire() -> None:
    """Snapshot enrichment mirrors linked_repos parsing."""
    agent = make_agent()
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            linked_repos=[
                {
                    "name": "sase-github",
                    "workspace_dir": "/tmp/sase-github_7",
                    "workspace_strategy": "suffix",
                }
            ]
        ),
        None,
        None,
    )

    assert agent.linked_repos == (
        LinkedRepoMetadata(
            name="sase-github",
            workspace_dir="/tmp/sase-github_7",
        ),
    )


def test_phase_parent_plan_reference_matches_filesystem_and_wire(
    tmp_path: Path,
) -> None:
    metadata = {
        "sdd_plan_path": "plans/authored-phase.md",
        "epic_plan_ref": "plans/parent-epic.md",
        "epic_bead_id": "sase-83",
        "phase_bead_id": "sase-83.1",
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(metadata))
    filesystem_agent = make_agent()
    wire_agent = make_agent()

    enrich_agent_from_meta(filesystem_agent, str(tmp_path))
    enrich_agent_from_meta_wire(
        wire_agent,
        AgentMetaWire(**metadata),
        None,
        None,
    )

    expected = (
        "plans/authored-phase.md",
        "plans/parent-epic.md",
        "sase-83",
        "sase-83.1",
    )
    assert (
        filesystem_agent.sdd_plan_path,
        filesystem_agent.epic_plan_ref,
        filesystem_agent.epic_bead_id,
        filesystem_agent.phase_bead_id,
    ) == expected
    assert (
        wire_agent.sdd_plan_path,
        wire_agent.epic_plan_ref,
        wire_agent.epic_bead_id,
        wire_agent.phase_bead_id,
    ) == expected


def test_source_machine_projection_matches_filesystem_and_wire(
    tmp_path: Path,
) -> None:
    metadata = {
        "pid": 1234,
        "source_machine": "apollo",
        "imported_source_owner": {"username": "bryan", "machine_name": "apollo"},
    }
    (tmp_path / "agent_meta.json").write_text(json.dumps(metadata))

    filesystem = make_agent()
    wire = make_agent()
    enrich_agent_from_meta(filesystem, str(tmp_path))
    enrich_agent_from_meta_wire(wire, AgentMetaWire(**metadata), None, None)
    assert filesystem.source_machine == "apollo"
    assert wire.source_machine == "apollo"
