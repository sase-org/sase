"""Family elapsed / current-run survival through fleet projection."""

from __future__ import annotations

from sase.ace.tui.models.agent_time import compute_leaf_row_runtime, compute_row_runtime
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from tests.ace.tui.fleet_fixture import fleet_host_response, fleet_summary

from ._fleet_display_parity_shared import _at


def test_remote_family_elapsed_and_current_run_survive_projection() -> None:
    started = 1_800_000_000.0
    run_started = 1_800_000_600.0
    observed = 1_800_001_200.0
    summary = fleet_summary(
        agent_id="elapsed-family",
        agent_name="elapsed-family",
        status="WORKING TALE",
        started_at_unix=started,
        run_started_at_unix=run_started,
        observed_at_unix=observed,
        family_id="elapsed-family",
        family_role="root",
    )
    child = fleet_summary(
        agent_id="elapsed-family--code",
        run_id="run-code",
        agent_name="elapsed-family--code",
        status="WORKING TALE",
        family_id="elapsed-family",
        family_role="member",
        parent_timestamp="run-1",
        started_at_unix=run_started,
        run_started_at_unix=run_started,
        observed_at_unix=observed,
    )
    response = fleet_host_response(
        alias="apollo",
        summaries=(summary, child),
        observed_at_unix=observed,
    )
    rows = list(project_fleet_agents(catalog_response=response).fleet_rows)
    root = next(row for row in rows if row.agent_name == "elapsed-family")
    assert root.start_time is not None
    assert root.run_start_time is not None
    assert root.run_start_time > root.start_time
    now = _at(observed)
    _ts, family_elapsed = compute_row_runtime(root, now=now)
    _leaf_ts, current_elapsed = compute_leaf_row_runtime(
        root.followup_agents[0] if root.followup_agents else root,
        now=now,
    )
    assert family_elapsed
    assert current_elapsed
    rendered = format_agent_option(
        root, 0, is_selected=False, now=now, show_machine_chip=True
    )[0].plain
    assert " / " in rendered or family_elapsed == current_elapsed
