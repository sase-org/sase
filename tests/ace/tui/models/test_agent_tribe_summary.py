"""Pure tribe-panel summary projection tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import (
    build_agent_tribe_summary_snapshot,
    _tribe_panel_identity,
)

_NOW = datetime(2026, 7, 18, 15, 0, 0)


def _agent(
    name: str,
    status: str,
    *,
    start_minute: int,
    clan: str | None = None,
    generation: str | None = None,
    family: str | None = None,
    role: str | None = None,
    parent: str | None = None,
) -> Agent:
    start = datetime(2026, 7, 18, 14, start_minute, 0)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/demo.sase",
        status=status,
        start_time=start,
        run_start_time=start,
        stop_time=_NOW if status in {"DONE", "FAILED"} else None,
        raw_suffix=f"suffix-{name}",
        agent_name=name,
        agent_clan=clan,
        agent_clan_generation=generation,
        agent_family=family,
        agent_family_role="root" if role == "plan" else role,
        role_suffix=f"--{role}" if role else None,
        plan_chain_root=role == "plan",
        parent_timestamp=parent,
        model="gpt-5",
    )


def _mixed_roots() -> tuple[list[Agent], dict[str, Agent]]:
    clan_member = _agent(
        "research.failed",
        "FAILED",
        start_minute=0,
        clan="research",
        generation="gen-1",
    )
    clan_member.error_message = "Build failed\nfull diagnostic"
    clan_member.output_variables = {"report": "summary\nfull report"}
    clan_container = project_clan_tree([clan_member])[0]

    family_root = _agent(
        "build--plan",
        "RUNNING",
        start_minute=5,
        family="build",
        role="plan",
    )
    family_child = _agent(
        "build--code",
        "WAITING",
        start_minute=10,
        family="build",
        role="code",
        parent=family_root.raw_suffix,
    )
    family_child.activity = "waiting on review"
    family_root.followup_agents = [family_child]

    standalone = _agent("standalone", "DONE", start_minute=20)
    standalone.step_output = {"meta_release_notes": "ready\nfull notes"}
    return [clan_container, family_root, family_child, standalone], {
        "clan": clan_container,
        "clan_member": clan_member,
        "family": family_root,
        "family_child": family_child,
        "standalone": standalone,
    }


def test_snapshot_preserves_mixed_unit_order_and_aggregates_loaded_rows() -> None:
    roots, rows = _mixed_roots()

    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        roots,
        panel_collapsed=True,
        unread_ids={rows["standalone"].identity},
        marked_ids={rows["family_child"].identity},
        now=_NOW,
    )

    assert snapshot.container_identity == _tribe_panel_identity("epic")
    assert snapshot.label == "@epic"
    assert snapshot.panel_collapsed is True
    assert [unit.kind for unit in snapshot.units] == ["clan", "family", "agent"]
    assert [unit.label for unit in snapshot.units] == [
        "research",
        "build",
        "standalone",
    ]
    assert snapshot.clan_count == 1
    assert snapshot.family_count == 1
    assert snapshot.agent_count == 4
    assert snapshot.nested_count == 2
    assert snapshot.runtime_span == "1h"
    assert snapshot.counts.failed == 1
    assert snapshot.counts.running == 1
    assert snapshot.counts.unread == 1
    assert snapshot.units[1].is_marked is True
    assert snapshot.units[2].is_unread is True
    assert [child.label for child in snapshot.units[1].children] == ["--code"]
    assert [entry.preview for entry in snapshot.errors] == ["Build failed"]
    assert [entry.name for entry in snapshot.output_variables] == ["report"]
    assert [entry.name for entry in snapshot.workflow_variables] == ["Release Notes"]


def test_attention_digest_and_untagged_identity_use_unit_statuses() -> None:
    roots, _rows = _mixed_roots()
    snapshot = build_agent_tribe_summary_snapshot(
        None,
        roots,
        panel_collapsed=False,
        now=_NOW,
    )

    assert snapshot.label == "(untagged)"
    assert snapshot.container_identity == ("panel", None)
    assert snapshot.panel_collapsed is False
    assert [(entry.unit_label, entry.preview) for entry in snapshot.attention] == [
        ("research", "Build failed")
    ]
