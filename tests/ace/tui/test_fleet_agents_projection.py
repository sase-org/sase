from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_live_query import agent_live_query_entry
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets._queue_weight_badge import append_agent_queue_badges
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from tests._fleet_contract_sase_core_rs_helpers import (
    _binding,
    _known_installation_id,
    _projection_request,
)
from tests.ace.tui.fleet_fixture import (
    fleet_attention_response,
    fleet_counts,
    fleet_follow_snapshot,
    fleet_host_response,
    fleet_installation_id,
    fleet_logical_locator,
    fleet_summary,
)


def test_project_fleet_agents_marks_followed_and_preserves_machine_sections() -> None:
    installation_id = fleet_installation_id("a")
    logical_a = fleet_logical_locator(
        installation_id=installation_id,
        project_id="sase",
        agent_id="agent-a",
    )
    first = fleet_summary(
        installation_id=installation_id,
        project_id="sase",
        project_name="SASE",
        agent_id="agent-a",
        run_id="run-a",
        agent_name="same.name",
        bounded_intent="hydrate",
        revision=4,
    )
    second = fleet_summary(
        installation_id=installation_id,
        project_id="sase",
        project_name="SASE",
        agent_id="agent-b",
        run_id="run-b",
        agent_name="same.name",
        status="done",
    )
    follow_snapshot = fleet_follow_snapshot(logical_a, path="/tmp/follows.json")
    response = fleet_host_response(
        alias="apollo",
        installation_id=installation_id,
        summaries=(first, second),
    )

    projection = project_fleet_agents(
        catalog_response=response,
        followed_response=response,
        follow_snapshot=follow_snapshot,
        local_agent_count=3,
    )

    assert len(projection.fleet_rows) == 2
    assert len(projection.focus_rows) == 1
    assert projection.counts["local"] == 3
    assert projection.counts["focus_total"] == 4
    assert projection.counts["fleet"] == 1
    followed = projection.focus_rows[0]
    assert followed.fleet_origin_alias == "apollo"
    assert followed.project_display_name == "SASE"
    assert followed.project_file == "/fleet/sase/project.yml"
    assert followed.fleet_followed is True
    assert followed.fleet_revision == 4
    assert followed.fleet_bounded_intent == "hydrate"
    assert {row.identity for row in projection.fleet_rows} == {
        row.identity for row in projection.fleet_rows
    }
    assert projection.fleet_rows[0].identity != projection.fleet_rows[1].identity


def test_project_fleet_agents_maps_pending_attention_onto_local_statuses() -> None:
    first = fleet_summary(agent_id="agent-a")
    second = fleet_summary(agent_id="agent-b", status="asking")
    response = fleet_host_response(alias="apollo", summaries=(first, second))
    attention_response = fleet_attention_response(
        (
            {
                "kind": "question",
                "state": "pending",
                "logical_key": first["logical_key"],
            },
            {
                "kind": "gate",
                "state": "settled",
                "logical_key": second["logical_key"],
            },
        ),
        alias="apollo",
    )

    projection = project_fleet_agents(
        catalog_response=response,
        attention_response=attention_response,
    )

    by_key = {row.fleet_logical_key: row for row in projection.fleet_rows}
    assert by_key[first["logical_key"]].status == "QUESTION"
    assert by_key[first["logical_key"]].fleet_attention == {
        "kind": "question",
        "state": "pending",
        "logical_key": first["logical_key"],
    }
    # A settled attention entry never overrides status; the row's own
    # lifecycle ("asking") is the fallback signal instead.
    assert by_key[second["logical_key"]].status == "WAITING INPUT"
    assert by_key[second["logical_key"]].fleet_attention is not None


def test_project_fleet_agents_carries_remote_queue_weight_without_local_charge() -> (
    None
):
    summary = fleet_summary(
        agent_id="weighted",
        agent_name="apollo.weighted",
        queue_weight=0.25,
        queue_weight_explicit=True,
    )
    response = {
        "schema_version": 1,
        "operation": "catalog",
        "configured_host_count": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": "apollo",
                "summaries": [summary],
            }
        ],
        "count_hosts": [],
    }

    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_weight == 0.25
    assert row.queue_weight_explicit is True
    assert row.queue_weight_invalid is False
    left, _, _ = format_agent_option(row, 0, is_selected=False)
    header, _ = build_header_text(row, cheap=True)
    assert "w0.25 (RUNNING)" in left.plain
    assert "apollo.weighted" in left.plain
    assert "Weight: 0.25 capacity units" in header.plain

    local = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="local",
        project_file="/tmp/project/project.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix="20260712120000",
        artifacts_dir="/tmp/project/artifacts/ace-run/20260712120000",
        pid=1234,
        run_start_time=datetime(2026, 7, 12, 12, 0, 0),
    )
    capacity = refresh_runner_slot_context([local, row], effective_limit=1)
    assert capacity.slots_in_use == 1
    assert capacity.occupied_capacity == 1.0


def test_project_fleet_agents_carries_remote_explicit_zero_queue_weight() -> None:
    """An explicit-zero remote weight (e.g. a remote epic-launch monitor) is

    valid and non-occupying -- unlike an implicit zero, which stays
    invalid/fail-closed like any other non-positive weight -- and never
    renders a misleading ``w0`` badge or "Weight: 0" header text.
    """
    summary = fleet_summary(
        agent_id="epic-launch-monitor",
        agent_name="apollo.epic-launch-monitor",
        queue_weight=0.0,
        queue_weight_explicit=True,
    )
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_weight == 0.0
    assert row.queue_weight_explicit is True
    assert row.queue_weight_invalid is False
    text = Text()
    assert append_agent_queue_badges(text, row) is False
    assert text.plain == ""
    header, _ = build_header_text(row, cheap=True)
    assert "Weight:" not in header.plain

    local = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="local",
        project_file="/tmp/project/project.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix="20260712120002",
        artifacts_dir="/tmp/project/artifacts/ace-run/20260712120002",
        pid=1236,
        run_start_time=datetime(2026, 7, 12, 12, 0, 0),
    )
    capacity = refresh_runner_slot_context([local, row], effective_limit=1)
    assert capacity.slots_in_use == 1
    assert capacity.occupied_capacity == 1.0


def test_project_fleet_agents_carries_remote_queue_capacity_without_local_charge() -> (
    None
):
    summary = fleet_summary(
        agent_id="capacitated",
        agent_name="apollo.capacitated",
        queue_capacity=100,
        queue_capacity_explicit=True,
    )
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_capacity == 100
    assert row.queue_capacity_explicit is True
    assert row.wait_runners == 100
    assert row.wait_runners_explicit is True
    left, _, _ = format_agent_option(row, 0, is_selected=False)
    header, _ = build_header_text(row, cheap=True)
    assert "c100 (RUNNING)" in left.plain
    assert "apollo.capacitated" in left.plain
    assert "Capacity: 100 capacity units" in header.plain

    local = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="local",
        project_file="/tmp/project/project.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix="20260712120001",
        artifacts_dir="/tmp/project/artifacts/ace-run/20260712120001",
        pid=1235,
        run_start_time=datetime(2026, 7, 12, 12, 0, 0),
    )
    capacity = refresh_runner_slot_context([local, row], effective_limit=1)
    assert capacity.slots_in_use == 1
    assert capacity.occupied_capacity == 1.0


def test_project_fleet_agents_carries_remote_explicit_zero_queue_capacity() -> None:
    summary = fleet_summary(
        agent_id="drained",
        agent_name="apollo.drained",
        queue_capacity=0,
        queue_capacity_explicit=True,
    )
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_capacity == 0
    assert row.queue_capacity_explicit is True
    left, _, _ = format_agent_option(row, 0, is_selected=False)
    header, _ = build_header_text(row, cheap=True)
    assert "c0 (RUNNING)" in left.plain
    assert "legacy 0" in header.plain


def test_project_fleet_agents_keeps_absent_queue_capacity_quiet() -> None:
    summary = fleet_summary(agent_id="unbudgeted", agent_name="apollo.unbudgeted")
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_capacity is None
    assert row.queue_capacity_explicit is False
    text = Text()
    assert append_agent_queue_badges(text, row) is False
    assert text.plain == ""
    header, _ = build_header_text(row, cheap=True)
    assert "Capacity:" not in header.plain


def test_project_fleet_agents_normalizes_legacy_owner_wait_runners_into_capacity() -> (
    None
):
    """An owner-side summary built from legacy ``wait_runners`` metadata already
    carries canonical ``queue_capacity`` by the time it reaches the fleet-row
    adapter; this proves the real projection boundary, not a hand-built fixture.
    """
    installation_id = _known_installation_id("a")
    request = _projection_request(installation_id, agent_id="legacy-capacity")
    request["record"]["agent_meta"]["wait_runners"] = 0
    request["record"]["agent_meta"]["wait_runners_explicit"] = True
    owner_summary = _binding("fleet_project_resolved_agent_summary")(request)
    assert owner_summary["queue_capacity"] == 0
    assert owner_summary["queue_capacity_explicit"] is True
    assert "wait_runners" not in owner_summary

    response = fleet_host_response(alias="apollo", summaries=(owner_summary,))
    projection = project_fleet_agents(catalog_response=response)
    row = projection.fleet_rows[0]

    assert row.queue_capacity == 0
    assert row.queue_capacity_explicit is True
    assert row.wait_runners == 0
    assert row.wait_runners_explicit is True
    header, _ = build_header_text(row, cheap=True)
    assert "legacy 0" in header.plain


def test_offline_fleet_fixture_projects_rows_counts_and_diagnostics() -> None:
    installation_id = fleet_installation_id("c")
    logical = fleet_logical_locator(
        installation_id=installation_id,
        agent_id="fixture-agent",
    )
    summary = fleet_summary(
        installation_id=installation_id,
        agent_id="fixture-agent",
        needs_attention=True,
        bounded_intent="reuse from visual and perf tests",
    )
    response = fleet_host_response(
        alias="apollo",
        installation_id=installation_id,
        summaries=(summary,),
        diagnostics=(
            {
                "code": "fixture_warning",
                "severity": "warning",
                "message": "offline fixture diagnostic",
            },
        ),
        partial=True,
    )
    attention = fleet_attention_response(
        (
            {
                "kind": "question",
                "state": "pending",
                "logical_key": summary["logical_key"],
            },
        ),
        alias="apollo",
    )

    projection = project_fleet_agents(
        summary_response=response,
        catalog_response=response,
        followed_response=response,
        attention_response=attention,
        follow_snapshot=fleet_follow_snapshot(logical),
        local_agent_count=2,
    )

    assert len(projection.fleet_rows) == 1
    assert len(projection.focus_rows) == 1
    assert projection.configured_host_count == 1
    assert projection.partial is True
    assert projection.counts["local"] == 2
    assert projection.counts["focus_total"] == 3
    assert projection.counts["fleet"] == 1
    assert [diagnostic["code"] for diagnostic in projection.diagnostics] == [
        "fixture_warning",
        "fleet_host_partial",
        "fixture_warning",
        "fleet_host_partial",
        "fixture_warning",
        "fleet_host_partial",
    ]
    row = projection.focus_rows[0]
    assert row.fleet_origin_alias == "apollo"
    assert row.fleet_followed is True
    assert row.status == "QUESTION"
    assert row.fleet_bounded_intent == "reuse from visual and perf tests"


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


def test_project_fleet_agents_sources_host_running_and_total_counts() -> None:
    """Every row from a host carries that host's own authoritative counts."""
    running = fleet_summary(agent_id="running-agent", status="running")
    done = fleet_summary(agent_id="done-agent", status="done")
    counts = fleet_counts((running, done), running=1)
    response = fleet_host_response(
        alias="apollo",
        summaries=(running, done),
        counts=counts,
    )

    projection = project_fleet_agents(catalog_response=response)

    assert len(projection.fleet_rows) == 2
    for row in projection.fleet_rows:
        assert row.fleet_host_running_count == 1
        assert row.fleet_host_total_count == 2


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
    summary = fleet_summary(status="running", started_at_unix=1_800_000_000.0)
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    row = projection.fleet_rows[0]
    assert row.start_time is not None
    assert row.run_start_time == row.start_time


def test_project_fleet_agents_prefers_owner_human_project_label() -> None:
    """The human project label wins over the raw portable project id."""
    summary = fleet_summary(project_name="gh_sase-org__sase", project_label="sase")
    response = fleet_host_response(alias="apollo", summaries=(summary,))

    projection = project_fleet_agents(catalog_response=response)

    assert projection.fleet_rows[0].project_display_name == "sase"


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
    members = [row for row in projection.fleet_rows if not row.is_clan_container]
    assert len(members) == 2
    assert all(member.agent_clan == "rename-fix" for member in members)
    assert all(member.clan_tribe == "core" for member in members)
    assert all(member.tribe == "core" for member in members)


def _remote_family_summaries() -> tuple[dict[str, object], ...]:
    root = fleet_summary(
        agent_id="remote-family",
        run_id="20260910120000",
        agent_name="remote-family",
        family_id="remote-family",
        family_role="root",
    )
    code = fleet_summary(
        agent_id="remote-family--code",
        run_id="20260910120100",
        agent_name="remote-family--code",
        family_id="remote-family",
        family_role="member",
        parent_timestamp="20260910120000",
    )
    monitor = fleet_summary(
        agent_id="remote-family--mon",
        run_id="20260910120200",
        agent_name="remote-family--mon",
        family_id="remote-family",
        family_role="monitor",
        row_kind="monitor",
        parent_timestamp="20260910120000",
        occupied_runner_slot=False,
    )
    gate = fleet_summary(
        agent_id="remote-family--gate",
        run_id="20260910120300",
        agent_name="remote-family--gate",
        family_id="remote-family",
        family_role="gate",
        row_kind="gate",
        parent_timestamp="20260910120000",
        occupied_runner_slot=False,
    )
    proc = fleet_summary(
        agent_id="remote-family--proc",
        run_id="20260910120400",
        agent_name="remote-family--proc",
        family_id="remote-family",
        family_role="proc",
        row_kind="proc",
        parent_timestamp="20260910120000",
        occupied_runner_slot=False,
    )
    return root, code, monitor, gate, proc


def _tree_shape(agents: list[Agent]) -> list[tuple[object, ...]]:
    return [
        (
            agent.identity,
            agent.parent_timestamp,
            agent.is_family_container_row,
            agent.is_clan_container,
            agent.is_remote_family_container,
            tuple(child.identity for child in agent.followup_agents),
            agent.fleet_origin_alias,
        )
        for agent in agents
    ]


def test_project_fleet_agents_builds_a_remote_family_container_with_shells() -> None:
    response = fleet_host_response(
        alias="apollo",
        summaries=_remote_family_summaries(),
    )

    projection = project_fleet_agents(catalog_response=response)
    rows = list(projection.fleet_rows)
    by_name = {row.agent_name: row for row in rows}
    root = by_name["remote-family"]
    code = by_name["remote-family--code"]
    monitor = by_name["remote-family--mon"]
    gate = by_name["remote-family--gate"]
    proc = by_name["remote-family--proc"]

    assert root.is_family_container_row is True
    assert root.fleet_origin_alias == "apollo"
    assert {child.agent_name for child in root.followup_agents} == {
        "remote-family--code",
        "remote-family--mon",
        "remote-family--gate",
        "remote-family--proc",
    }
    assert code.is_family_member_child is True
    assert monitor.is_monitor is True
    assert gate.is_gate is True
    assert proc.is_proc_shell is True
    assert all(
        child.parent_timestamp == root.raw_suffix for child in root.followup_agents
    )
    left, _, _ = format_agent_option(root, 0, is_selected=False)
    assert "[agent]" not in left.plain
    from sase.ace.tui.widgets._agent_list_helpers import compute_fold_annotation

    annotation = compute_fold_annotation(
        root,
        {root.raw_suffix: (len(root.followup_agents), 0)},
        set(),
    )
    assert annotation.startswith(" ×")


def test_project_fleet_agents_drops_container_plus_concrete_duplicates() -> None:
    concrete = fleet_summary(
        agent_id="sase-zr.1",
        run_id="run-current",
        agent_name="sase-zr.1",
        family_id="sase-zr",
        family_role="root",
        current_instance=True,
        revision=4,
    )
    container = fleet_summary(
        agent_id="sase-zr.1",
        run_id="run-container",
        agent_name="sase-zr.1",
        family_id="sase-zr",
        family_role="root",
        row_kind="container_header",
        current_instance=False,
        container_projected_concrete_agent=True,
        revision=3,
    )
    member = fleet_summary(
        agent_id="sase-zr.1--code",
        run_id="run-code",
        agent_name="sase-zr.1--code",
        family_id="sase-zr",
        family_role="member",
        parent_timestamp="run-current",
    )
    response = fleet_host_response(
        alias="apollo",
        summaries=(container, concrete, member),
    )

    projection = project_fleet_agents(catalog_response=response)
    names = [row.agent_name for row in projection.fleet_rows]
    assert names.count("sase-zr.1") == 1
    root = next(row for row in projection.fleet_rows if row.agent_name == "sase-zr.1")
    assert root.fleet_current_instance is True
    assert root.fleet_row_kind == "agent_shell"
    assert root.is_family_container_row is True


def test_project_fleet_agents_drops_superseded_non_current_top_level_instances() -> (
    None
):
    current = fleet_summary(
        agent_id="solo",
        run_id="run-new",
        agent_name="solo",
        family_id=None,
        current_instance=True,
        revision=5,
    )
    stale = fleet_summary(
        agent_id="solo",
        run_id="run-old",
        agent_name="solo",
        family_id=None,
        current_instance=False,
        status="done",
        revision=2,
    )
    historical = fleet_summary(
        agent_id="solo",
        run_id="run-history",
        agent_name="solo--old",
        family_id="solo",
        family_role="historical_shell",
        row_kind="historical_shell",
        current_instance=False,
        parent_timestamp="run-new",
        status="done",
        revision=1,
    )
    response = fleet_host_response(
        alias="apollo",
        summaries=(stale, current, historical),
    )

    projection = project_fleet_agents(catalog_response=response)
    by_name = {row.agent_name: row for row in projection.fleet_rows}
    assert "solo" in by_name
    assert by_name["solo"].fleet_current_instance is True
    assert "solo--old" in by_name
    assert by_name["solo--old"].parent_timestamp == by_name["solo"].raw_suffix
    assert [row.agent_name for row in projection.fleet_rows].count("solo") == 1


def test_project_fleet_agents_synthesizes_a_stable_root_when_page_omits_it() -> None:
    code = fleet_summary(
        agent_id="crew--code",
        run_id="20260910120100",
        agent_name="crew--code",
        family_id="crew",
        family_role="member",
        parent_timestamp="20260910120000",
    )
    monitor = fleet_summary(
        agent_id="crew--mon",
        run_id="20260910120200",
        agent_name="crew--mon",
        family_id="crew",
        family_role="monitor",
        row_kind="monitor",
        parent_timestamp="20260910120000",
        occupied_runner_slot=False,
    )
    response = fleet_host_response(alias="apollo", summaries=(code, monitor))

    first = project_fleet_agents(catalog_response=response)
    second = project_fleet_agents(catalog_response=response)
    roots = [row for row in first.fleet_rows if not row.is_family_member_child]
    assert len(roots) == 1
    container = roots[0]
    assert container.is_remote_family_container is True
    assert container.is_family_container_row is True
    assert container.agent_family == "crew"
    assert container.raw_suffix == "fleet:apollo:family:crew"
    assert container.identity == second.fleet_rows[0].identity or any(
        row.identity == container.identity for row in second.fleet_rows
    )
    assert _tree_shape(list(first.fleet_rows)) == _tree_shape(list(second.fleet_rows))


def test_project_fleet_agents_preserves_selection_identity_across_refresh() -> None:
    response = fleet_host_response(
        alias="apollo",
        summaries=_remote_family_summaries(),
    )
    first = project_fleet_agents(catalog_response=response)
    selected = next(row for row in first.fleet_rows if row.is_family_container_row)
    second = project_fleet_agents(catalog_response=response)
    assert any(row.identity == selected.identity for row in second.fleet_rows)
    assert _tree_shape(list(first.fleet_rows)) == _tree_shape(list(second.fleet_rows))


def test_project_mixed_agent_tree_matches_reproject_and_refilter_shapes() -> None:
    from sase.ace.tui.actions.agents._fleet_projection import AgentFleetProjectionMixin
    from sase.ace.tui.models._agent_tree import project_mixed_agent_tree

    local = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="research.one",
        project_file="/tmp/sase.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 17, 10, 0, 0),
        raw_suffix="local-one",
        agent_name="research.one",
        agent_clan="research",
        agent_clan_generation="g1",
    )
    local_peer = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="research.two",
        project_file="/tmp/sase.sase",
        status="DONE",
        start_time=datetime(2026, 7, 17, 10, 1, 0),
        raw_suffix="local-two",
        agent_name="research.two",
        agent_clan="research",
        agent_clan_generation="g1",
    )
    remote = list(
        project_fleet_agents(
            catalog_response=fleet_host_response(
                alias="apollo",
                summaries=_remote_family_summaries(),
            )
        ).fleet_rows
    )
    expected = project_mixed_agent_tree([local, local_peer], remote)
    assert any(row.is_clan_container for row in expected)
    assert any(
        row.is_family_container_row and row.fleet_origin_alias == "apollo"
        for row in expected
    )

    class _Harness(AgentFleetProjectionMixin):
        def __init__(self) -> None:
            self.current_agents_subtab = "focus"
            self.current_tab = "agents"
            self.current_idx = 0
            self._agents = [local]
            self._agents_with_children = [local, local_peer]
            self._agents_local_with_children = [local, local_peer]
            self._agents_fleet_rows = remote
            self._agents_refresh_active_source = "unknown"

        def _fleet_rows_with_dispatch_provisionals(
            self, rows: list[Agent]
        ) -> list[Agent]:
            return rows

        def _finalize_agent_list(self, *_args: object, **_kwargs: object) -> None:
            self._agents = list(self._agents_with_children)

        def _update_agents_header(self) -> None:
            return None

    harness = _Harness()
    harness._reproject_agents_from_current_mode(source="fleet_refresh")
    assert _tree_shape(harness._agents_with_children) == _tree_shape(expected)
    refiltered = harness._agents_source_for_current_mode(
        list(harness._agents_local_with_children)
    )
    assert _tree_shape(refiltered) == _tree_shape(expected)
