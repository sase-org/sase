"""New-shape fleet key coverage: the agent-session keys are read first.

The end-to-end tests use core-valid exclusive shapes (the core validates
the two spellings as aliases and rejects both together). The helper tests
feed both spellings with different values to prove the read order in the
model ``or``-chains directly.
"""

from __future__ import annotations

from sase.ace.tui.models._fleet_agents_identity import agent_session_name
from sase.ace.tui.models._fleet_agents_nodes import _is_history_or_nested
from sase.ace.tui.models._fleet_agents_promotion import _locator_wire
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from tests.ace.tui.fleet_fixture import fleet_host_response, fleet_summary


def _new_shape_root() -> dict[str, object]:
    return fleet_summary(
        agent_id="crew",
        run_id="20260910120000",
        agent_name="crew",
        legacy_family_id=None,
        agent_session_id="crew",
        agent_session_role="root",
    )


def test_new_shape_keys_project_agent_session_tree() -> None:
    root = _new_shape_root()
    code = fleet_summary(
        agent_id="crew--code",
        run_id="20260910120100",
        agent_name="crew--code",
        legacy_family_id=None,
        agent_session_id="crew",
        agent_session_role="member",
        parent_timestamp="20260910120000",
    )
    projection = project_fleet_agents(
        catalog_response=fleet_host_response(alias="apollo", summaries=(root, code))
    )
    by_name = {row.agent_name: row for row in projection.fleet_rows}
    root_row = by_name["crew"]
    code_row = by_name["crew--code"]
    assert root_row.is_agent_session_container_row is True
    assert root_row.agent_session_role == "root"
    assert code_row.agent_session == "crew"
    assert code_row.agent_session_role == "member"
    assert code_row.is_agent_session_member_child is True
    assert code_row in root_row.followup_agents


def test_rows_projection_reads_agent_session_role() -> None:
    summary = fleet_summary(
        agent_id="crew--mon",
        run_id="20260910120200",
        agent_name="crew--mon",
        legacy_family_id=None,
        agent_session_id="crew",
        agent_session_role="monitor",
        row_kind="monitor",
        parent_timestamp="20260910120000",
    )
    projection = project_fleet_agents(
        catalog_response=fleet_host_response(
            alias="apollo", summaries=(_new_shape_root(), summary)
        )
    )
    by_name = {row.agent_name: row for row in projection.fleet_rows}
    monitor_row = by_name["crew--mon"]
    assert monitor_row.agent_session_role == "monitor"
    assert monitor_row.is_monitor is True


def test_agent_session_name_reads_session_keys_first() -> None:
    labels = {"session_label": "new-crew", "family_label": "old-crew"}
    locator = {"agent_session_id": "new-crew", "family_id": "old-crew"}
    assert (
        agent_session_name(
            {}, labels, locator, session_role="member", parent_timestamp=None
        )
        == "new-crew"
    )
    assert (
        agent_session_name(
            {"agent_session": "explicit"},
            labels,
            locator,
            session_role="member",
            parent_timestamp=None,
        )
        == "explicit"
    )
    assert (
        agent_session_name(
            {},
            {"family_label": "old-crew"},
            {"family_id": "old-crew"},
            session_role="member",
            parent_timestamp=None,
        )
        == "old-crew"
    )


def test_nodes_nested_check_reads_agent_session_role_first() -> None:
    assert (
        _is_history_or_nested(
            {
                "row_kind": "agent_shell",
                "agent_session_role": "root",
                "family_role": "member",
            }
        )
        is False
    )
    assert (
        _is_history_or_nested(
            {
                "row_kind": "agent_shell",
                "agent_session_role": "member",
                "family_role": "root",
            }
        )
        is True
    )


def test_promotion_locator_wire_reads_agent_session_id_first() -> None:
    locator = {
        "schema_version": 1,
        "project": {
            "schema_version": 1,
            "origin": {
                "schema_version": 1,
                "installation_id": "sase_inst_v1_" + "a" * 64,
            },
            "project_id": "sase-main",
        },
        "agent_id": "worker",
        "agent_session_id": "new-crew",
        "family_id": "old-crew",
    }
    wire = _locator_wire(locator)
    assert wire is not None
    assert wire["agent_session_id"] == "new-crew"
    assert "family_id" not in wire
    legacy_wire = _locator_wire(
        {k: v for k, v in locator.items() if k != "agent_session_id"}
    )
    assert legacy_wire is not None
    assert legacy_wire["agent_session_id"] == "old-crew"
