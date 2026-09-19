from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_live_query import agent_live_query_entry
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from tests.ace.tui.fleet_fixture import (
    fleet_exact_key,
    fleet_host_response,
    fleet_summary,
)


def test_project_fleet_agents_never_renders_running_for_a_dead_liveness_row() -> None:
    """A definitively-dead owner liveness never presents as RUNNING.

    Simulates a demoted dead-active-tier record: the raw display status
    still says "running" (sase-core's ``status_for_record`` does not
    consult liveness), but the owner-resolved ``liveness``/``status_bucket``
    already say the process is gone. The viewer must not fabricate an
    active state from the stale status text.
    """
    summary = fleet_summary(status="running")
    summary["liveness"] = "dead"
    summary["status_bucket"] = "stopped"
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    assert len(projection.fleet_rows) == 1
    row = projection.fleet_rows[0]
    assert row.status == "WAS RUNNING"
    assert row.status_bucket == "Stopped"


def test_project_fleet_agents_keeps_running_for_alive_liveness() -> None:
    """A genuinely alive/running row keeps its ordinary RUNNING status."""
    summary = fleet_summary(status="running")
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    row = projection.fleet_rows[0]
    assert row.status == "RUNNING"
    assert row.status_bucket == "Running"


def test_project_fleet_agents_carries_remote_family_lineage_into_agent_rows() -> None:
    """Remote family metadata feeds the common Agent model and agents-live."""
    root = fleet_summary(
        agent_id="family-root",
        run_id="20260910120000",
        agent_name="remote-family",
        family_id="remote-family",
    )
    root["family_role"] = "root"
    child = fleet_summary(
        agent_id="family-code",
        run_id="20260910120100",
        agent_name="remote-family--code",
        family_id="remote-family",
    )
    child["family_role"] = "member"
    child["parent_timestamp"] = "20260910120000"
    response = fleet_host_response(alias="apollo", summaries=(root, child))

    projection = project_fleet_agents(catalog_response=response)

    by_name = {row.agent_name: row for row in projection.fleet_rows}
    root_row = by_name["remote-family"]
    child_row = by_name["remote-family--code"]
    assert root_row.agent_family is None
    assert root_row.agent_family_role == "root"
    assert child_row.agent_family == "remote-family"
    assert child_row.agent_family_role == "member"
    assert child_row.role_suffix == "--code"
    assert child_row.parent_timestamp == root_row.raw_suffix
    assert child_row.is_family_member_child is True
    assert root_row.is_family_container_row is True
    assert child_row in root_row.followup_agents
    entry = agent_live_query_entry(child_row)
    assert entry["fields"]["kind"] == ("member",)
    assert entry["fields"]["role"] == ("member", "code")
    assert entry["fields"]["family"] == ("remote-family",)


def test_project_fleet_agents_downgrades_fresh_chip_for_a_cached_aged_host() -> None:
    """A cached, aged client response must not render the fresh chip.

    The owner honestly stamped this row "fresh" at build time, but the
    viewer's own federation-worker cache is serving a copy fetched 120s
    ago, well past the fresh/stale thresholds - the rendered freshness must
    reflect the worse (viewer) signal, not the owner's stamp alone.
    """
    summary = fleet_summary(status="running", freshness="fresh")
    response = fleet_host_response(
        alias="apollo", summaries=(summary,), freshness="fresh"
    )
    response["hosts"][0]["cached"] = True
    response["hosts"][0]["age_seconds"] = 120.0

    projection = project_fleet_agents(catalog_response=response)

    assert projection.fleet_rows[0].fleet_freshness == "stale"


def test_project_fleet_agents_keeps_fresh_chip_for_a_live_fetch() -> None:
    """A live (non-cached) fetch keeps the owner's honest freshness stamp."""
    summary = fleet_summary(status="running", freshness="fresh")
    response = fleet_host_response(
        alias="apollo", summaries=(summary,), freshness="fresh"
    )

    projection = project_fleet_agents(catalog_response=response)

    assert projection.fleet_rows[0].fleet_freshness == "fresh"


def test_project_fleet_agents_sets_run_start_time_for_active_duration() -> None:
    """A running remote row must render a real duration, not ``0s``.

    ``leaf_runtime_interval`` needs ``run_start_time`` to compute an active
    row's elapsed time; without it a live remote row renders no runtime
    suffix at all.
    """
    summary = fleet_summary(
        status="running",
        started_at_unix=1_800_000_000.0,
        run_started_at_unix=1_800_000_030.0,
        observed_at_unix=1_800_000_090.0,
    )
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    row = projection.fleet_rows[0]
    assert row.start_time is not None
    assert row.run_start_time is not None
    assert row.run_start_time > row.start_time
    assert row.fleet_observed_at_unix is not None
    assert row.fleet_observed_at_unix >= 1_800_000_030.0


def test_project_fleet_agents_falls_back_to_started_at_for_legacy_runtime() -> None:
    summary = fleet_summary(status="running", started_at_unix=1_800_000_000.0)
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    row = projection.fleet_rows[0]
    assert row.start_time is not None
    assert row.run_start_time == row.start_time


def test_project_fleet_agents_keeps_legacy_summaries_without_schema_v4_fields() -> None:
    """Older gateways that omit additive v4 fields still render a row."""
    summary = fleet_summary(status="running", agent_id="legacy-solo", family_id=None)
    for field in (
        "started_at_unix",
        "run_started_at_unix",
        "stopped_at_unix",
        "tribe",
        "clan_tribe",
        "agent_clan",
        "parent_timestamp",
    ):
        summary.pop(field, None)
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    assert len(projection.fleet_rows) == 1
    row = projection.fleet_rows[0]
    assert row.agent_name == "legacy-solo"
    assert row.start_time is not None
    assert row.run_start_time == row.start_time
    assert row.tribe is None
    assert row.parent_timestamp is None
    assert not row.is_remote_family_container


def test_project_fleet_agents_prefers_owner_human_project_label() -> None:
    """The human project label wins over the raw portable project id."""
    summary = fleet_summary(project_name="gh_sase-org__sase", project_label="sase")
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    assert projection.fleet_rows[0].project_display_name == "sase"


def test_project_fleet_agents_does_not_render_exact_attempt_as_name() -> None:
    """Missing labels fall back to the logical agent id, not attempt internals."""
    summary = fleet_summary(agent_id="sase", run_id="20260915123456")
    summary["labels"].pop("agent_label")
    summary["exact_locator"]["attempt_id"] = "attempt-0"
    summary["exact_key"] = fleet_exact_key(summary["exact_locator"])
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    row = projection.fleet_rows[0]
    assert row.agent_name == "sase"
    assert "attempt-0" in (row.raw_suffix or "")
    rendered = format_agent_option(
        row,
        0,
        is_selected=False,
        now=datetime(2026, 9, 15, 12, 0),
        show_machine_chip=True,
    )[0].plain
    assert "sase" in rendered
    assert "attempt-0" not in rendered


def test_project_fleet_agents_sets_workspace_num() -> None:
    summary = fleet_summary(status="running", workspace_num=3)
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    assert projection.fleet_rows[0].workspace_num == 3


def test_project_fleet_agents_remote_clan_members_group_under_one_container() -> None:
    """Remote rows sharing clan identity already fold under one container.

    Local agents fold same-clan rows into one synthetic container via
    ``project_clan_tree``; ``normalize_remote_host_nodes`` routes remote
    rows through the identical shared pass, so this must already have
    happened by the time ``project_fleet_agents`` returns.
    """
    first = fleet_summary(
        agent_id="agent-a",
        run_id="run-a",
        agent_clan="rename-fix",
        agent_clan_generation="20260910120000",
        clan_tribe="core",
        tribe="core",
    )
    second = fleet_summary(
        agent_id="agent-b",
        run_id="run-b",
        agent_clan="rename-fix",
        agent_clan_generation="20260910120000",
        clan_tribe="core",
        tribe="core",
    )
    response = fleet_host_response(alias="apollo", summaries=(first, second))

    projection = project_fleet_agents(catalog_response=response)

    containers = [row for row in projection.fleet_rows if row.is_clan_container]
    assert len(containers) == 1
    assert containers[0].agent_clan == "rename-fix"
    assert containers[0].agent_clan_generation == "20260910120000"
    assert containers[0].fleet_origin_alias == "apollo"
    members = [row for row in projection.fleet_rows if not row.is_clan_container]
    assert len(members) == 2
    assert all(member.agent_clan == "rename-fix" for member in members)
    assert all(member.clan_tribe == "core" for member in members)
    assert all(member.tribe == "core" for member in members)
