"""Default-tribe panel counts for remote fleet rows."""

from __future__ import annotations

from sase.ace.tui.actions.agents._display_panel_titles import (
    agent_panel_border_title,
    agent_panel_counts,
)
from sase.ace.tui.models.agent_panels import agents_for_panel
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from tests.ace.tui.fleet_fixture import (
    fleet_host_response,
    fleet_installation_id,
    fleet_summary,
)

from ._fleet_display_parity_shared import (
    _PARITY_INTENT,
    _PARITY_REMOTE_ALIAS,
    _PARITY_STARTED_AT,
)


def test_remote_default_tribe_panel_counts_include_done_lanes() -> None:
    """A mixed remote panel uses the shared family/clan counters, including done."""
    installation_id = fleet_installation_id("a")

    def summary(agent_id: str, run_id: str, status: str, **overrides: object) -> dict:
        payload: dict[str, object] = {
            "installation_id": installation_id,
            "project_id": "sase-main",
            "project_name": "SASE",
            "agent_id": agent_id,
            "run_id": run_id,
            "agent_name": agent_id,
            "status": status,
            "bounded_intent": _PARITY_INTENT,
            "started_at_unix": _PARITY_STARTED_AT,
        }
        payload.update(overrides)
        return fleet_summary(**payload)  # type: ignore[arg-type]

    response = fleet_host_response(
        alias=_PARITY_REMOTE_ALIAS,
        installation_id=installation_id,
        summaries=(
            summary("run.one", "run-one", "RUNNING", family_id=None),
            summary(
                "wait.one",
                "wait-one",
                "WAITING",
                family_id=None,
                started_at_unix=_PARITY_STARTED_AT + 60,
            ),
            summary(
                "done.family",
                "done-root",
                "TALE DONE",
                family_id="done.family",
                family_role="root",
                started_at_unix=_PARITY_STARTED_AT - 4000,
                stopped_at_unix=_PARITY_STARTED_AT - 2000,
                current_instance=False,
            ),
            summary(
                "done.family--old",
                "done-old",
                "TALE DONE",
                family_id="done.family",
                family_role="historical_shell",
                row_kind="historical_shell",
                parent_timestamp="done-root",
                started_at_unix=_PARITY_STARTED_AT - 4000,
                stopped_at_unix=_PARITY_STARTED_AT - 3000,
                current_instance=False,
            ),
            summary(
                "done.two",
                "done-two",
                "DONE",
                family_id=None,
                started_at_unix=_PARITY_STARTED_AT - 1800,
                stopped_at_unix=_PARITY_STARTED_AT - 1200,
                current_instance=False,
            ),
            summary(
                "done.three",
                "done-three",
                "DONE",
                family_id=None,
                started_at_unix=_PARITY_STARTED_AT - 900,
                stopped_at_unix=_PARITY_STARTED_AT - 600,
                current_instance=False,
            ),
            summary(
                "done.four",
                "done-four",
                "DONE",
                family_id=None,
                started_at_unix=_PARITY_STARTED_AT - 500,
                stopped_at_unix=_PARITY_STARTED_AT - 400,
                current_instance=False,
            ),
        ),
    )
    rows = list(project_fleet_agents(catalog_response=response).fleet_rows)
    counts = agent_panel_counts(agents_for_panel(rows, None), set())
    title = agent_panel_border_title(None, counts.lane_count, counts=counts)
    assert counts.lane_count == 6
    assert (counts.running, counts.waiting, counts.read) == (1, 1, 4)
    assert "[R1 W1 D4]" in title.plain
    nested = [row for row in rows if row.agent_name == "done.family--old"]
    assert nested and nested[0].is_family_member_child
