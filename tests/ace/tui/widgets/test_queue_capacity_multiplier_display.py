"""Multiplier-capacity display: badges, header, wait lane, queue ladder, JSON."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.models._agent_runner_slot_capacity import (
    capacity_record_from_agent,
)
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_runner_slots import (
    RunnerCapacitySnapshot,
    RunnerQueueEntry,
)
from sase.ace.tui.widgets._agent_list_render_cache import agent_render_key
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets._queue_weight_badge import (
    QUEUE_CAPACITY_BADGE_NUMBER_STYLE,
    QUEUE_CAPACITY_BADGE_OVER_LIMIT_STYLE,
    append_agent_queue_badges,
    format_queue_capacity_badge_value,
    queue_capacity_badge_number_style,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_queue_section import (
    _queue_entry_capacity_badge_width,
)
from sase.ace.tui.widgets.prompt_panel._agent_wait_section import build_wait_lanes
from sase.agents.cli_list import _agent_to_json
from sase.core.agent_scan_wire import AgentMetaWire, WaitingMarkerWire
from sase.integrations._agent_list_entry_builder import build_agent_list_entry
from tests._agent_list_entries_helpers import agent as cli_agent
from tests._agent_list_entries_helpers import record as cli_record
from tests.ace.tui.widgets._agent_display_helpers import make_agent

_OVER_LIMIT = QUEUE_CAPACITY_BADGE_OVER_LIMIT_STYLE


def _multiplier_agent(**overrides):
    arguments = {
        "status": "QUEUED",
        "agent_name": "alpha",
        "queue_capacity_multiplier": 1.5,
        "queue_capacity_explicit": True,
        "slot_requested_at": "2026-07-25T12:00:00Z",
        "runner_effective_limit": 5.0,
    }
    arguments.update(overrides)
    return make_agent(**arguments)


def test_badge_value_formats_multiplier() -> None:
    assert (
        format_queue_capacity_badge_value(None, explicit=True, multiplier=1.5) == "1.5x"
    )
    assert (
        format_queue_capacity_badge_value(None, explicit=False, multiplier=1.5)
        == "1.5x"
    )
    assert (
        format_queue_capacity_badge_value(None, explicit=True, multiplier=None) is None
    )


def test_badge_value_prefers_integer_when_both_present() -> None:
    assert format_queue_capacity_badge_value(4, explicit=True, multiplier=1.5) == "4"


def test_badge_style_marks_multiplier_above_one_over_limit() -> None:
    assert (
        queue_capacity_badge_number_style(
            None, explicit=True, effective_limit=5.0, multiplier=1.5
        )
        == _OVER_LIMIT
    )
    assert (
        queue_capacity_badge_number_style(
            None, explicit=True, effective_limit=5.0, multiplier=0.5
        )
        == QUEUE_CAPACITY_BADGE_NUMBER_STYLE
    )
    assert (
        queue_capacity_badge_number_style(
            None, explicit=False, effective_limit=5.0, multiplier=1.5
        )
        == _OVER_LIMIT
    )


def test_agent_row_renders_multiplier_badge() -> None:
    text = Text()
    assert append_agent_queue_badges(text, _multiplier_agent()) is True
    assert "c1.5x" in text.plain


def test_queued_row_renders_multiplier_badge() -> None:
    left, _, _ = format_agent_option(
        _multiplier_agent(
            runner_slot_queue_position=2,
            runner_slot_queue_size=3,
        ),
        0,
        is_selected=False,
    )

    assert "c1.5x" in left.plain


def test_detail_header_shows_multiplier_budget_and_resolved_units() -> None:
    header, _ = build_header_text(_multiplier_agent(), cheap=True)

    assert "1.5x budget (7.5 capacity units)" in header.plain


def test_wait_lane_shows_multiplier_budget_and_resolved_units() -> None:
    lanes = build_wait_lanes(
        _multiplier_agent(),
        agent_status_buckets=None,
        clan_wait_member_statuses=None,
        tribe_wait_bindings=None,
        wait_bead_statuses=None,
    )

    capacity = next(value for tag, value in lanes if tag == "capacity")
    assert "capacity budget 1.5x (7.5)" in capacity.plain


def test_queue_ladder_entry_badges_multiplier() -> None:
    entry = RunnerQueueEntry(
        identity=(AgentType.RUNNING, "alpha", "alpha"),
        presented_name="alpha",
        threshold=None,
        wait_runners_explicit=True,
        capacity_multiplier=1.5,
        priority=10,
        slot_requested_at="2026-07-25T12:00:00Z",
        status="QUEUED",
    )

    assert _queue_entry_capacity_badge_width(entry) > 0

    text = Text()
    agent = _multiplier_agent(
        cl_name="alpha",
        raw_suffix="alpha",
        agent_name="alpha",
        runner_slot_queue_position=1,
        runner_slot_queue_size=1,
    )
    assert append_agent_queue_badges(text, agent) is True
    assert "c1.5x" in text.plain

    header, _ = build_header_text(
        agent,
        cheap=True,
        runner_capacity=RunnerCapacitySnapshot(
            effective_limit=5.0,
            slots_in_use=1,
            queued_count=1,
            queue=(entry,),
            occupied_capacity=1.0,
        ),
    )
    assert "c1.5x" in header.plain


def test_render_key_changes_when_multiplier_changes() -> None:
    first = agent_render_key(
        _multiplier_agent(),
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    second = agent_render_key(
        _multiplier_agent(queue_capacity_multiplier=0.5),
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    integer = agent_render_key(
        make_agent(
            status="QUEUED",
            queue_capacity=4,
            queue_capacity_explicit=True,
            wait_runners=4,
            wait_runners_explicit=True,
            slot_requested_at="2026-07-25T12:00:00Z",
            runner_effective_limit=5.0,
        ),
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    assert first != second
    assert first != integer


def test_capacity_record_carries_multiplier() -> None:
    record = capacity_record_from_agent(_multiplier_agent(), {})

    assert record["queue_capacity_multiplier"] == 1.5
    assert record["queue_capacity"] is None
    assert record["queue_capacity_explicit"] is True


def test_agent_list_entry_and_json_expose_multiplier() -> None:
    entry = build_agent_list_entry(
        cli_agent(status="WAITING"),
        record=cli_record(
            agent_meta=AgentMetaWire(
                queue_capacity_multiplier=1.5,
                queue_capacity_explicit=True,
            ),
            waiting=WaitingMarkerWire(
                queue_capacity_multiplier=1.5,
                queue_capacity_explicit=True,
                slot_requested_at="2026-07-25T12:00:00Z",
            ),
        ),
    )

    assert entry.wait.queue_capacity_multiplier == 1.5
    assert entry.wait.queue_capacity is None

    payload = _agent_to_json(entry)
    assert payload["queue_capacity_multiplier"] == 1.5
    assert payload["queue_capacity"] is None


def test_agent_list_entry_prefers_integer_over_multiplier() -> None:
    entry = build_agent_list_entry(
        cli_agent(status="WAITING"),
        record=cli_record(
            agent_meta=AgentMetaWire(
                queue_capacity=4,
                queue_capacity_explicit=True,
                queue_capacity_multiplier=1.5,
            ),
        ),
    )

    assert entry.wait.queue_capacity == 4
    assert entry.wait.queue_capacity_multiplier is None


def _loaded_multiplier_agent(**overrides):
    """Loader-shaped agent: multiplier persisted without the explicit flag."""
    arguments = {
        "status": "QUEUED",
        "agent_name": "alpha",
        "queue_capacity_multiplier": 1.5,
        "queue_capacity_explicit": False,
        "slot_requested_at": "2026-07-25T12:00:00Z",
        "runner_effective_limit": 5.0,
    }
    arguments.update(overrides)
    return make_agent(**arguments)


def test_loaded_multiplier_renders_badge_header_and_wait_lane() -> None:
    agent = _loaded_multiplier_agent()

    text = Text()
    assert append_agent_queue_badges(text, agent) is True
    assert "c1.5x" in text.plain

    header, _ = build_header_text(agent, cheap=True)
    assert "1.5x budget (7.5 capacity units)" in header.plain

    lanes = build_wait_lanes(
        agent,
        agent_status_buckets=None,
        clan_wait_member_statuses=None,
        tribe_wait_bindings=None,
        wait_bead_statuses=None,
    )
    capacity = next(value for tag, value in lanes if tag == "capacity")
    assert "capacity budget 1.5x (7.5)" in capacity.plain


def test_loaded_multiplier_capacity_record_stays_implicit() -> None:
    record = capacity_record_from_agent(_loaded_multiplier_agent(), {})

    assert record["queue_capacity_multiplier"] == 1.5
    assert record["queue_capacity"] is None
    assert record["queue_capacity_explicit"] is False


def test_queue_ladder_entry_badges_implicit_multiplier() -> None:
    entry = RunnerQueueEntry(
        identity=(AgentType.RUNNING, "alpha", "alpha"),
        presented_name="alpha",
        threshold=None,
        wait_runners_explicit=False,
        capacity_multiplier=1.5,
        priority=10,
        slot_requested_at="2026-07-25T12:00:00Z",
        status="QUEUED",
    )

    assert _queue_entry_capacity_badge_width(entry) > 0

    text = Text()
    agent = _loaded_multiplier_agent(
        cl_name="alpha",
        raw_suffix="alpha",
        agent_name="alpha",
        runner_slot_queue_position=1,
        runner_slot_queue_size=1,
    )
    assert append_agent_queue_badges(text, agent) is True
    assert "c1.5x" in text.plain


def test_waiting_digests_show_loaded_multiplier() -> None:
    from sase.ace.tui.models._agent_clan_sections import build_agent_member_digest
    from sase.ace.tui.widgets.prompt_panel._member_roster_digest import (
        agent_roster_digest,
    )

    agent = _loaded_multiplier_agent()
    clan_digest = build_agent_member_digest(
        agent, label=".alpha", agent_session_depth=0
    )
    assert "c1.5x" in clan_digest.waiting
    assert "c1.5x" in agent_roster_digest(agent).waiting

    integer_agent = make_agent(
        status="QUEUED",
        agent_name="alpha",
        wait_runners=4,
        slot_requested_at="2026-07-25T12:00:00Z",
        runner_effective_limit=5.0,
    )
    integer_digest = build_agent_member_digest(
        integer_agent, label=".alpha", agent_session_depth=0
    )
    assert "c4" in integer_digest.waiting
    assert "c4" in agent_roster_digest(integer_agent).waiting


def test_implicit_integer_capacity_renders_no_badge() -> None:
    agent = make_agent(
        status="QUEUED",
        agent_name="alpha",
        queue_capacity=4,
        queue_capacity_explicit=False,
        wait_runners=4,
        wait_runners_explicit=False,
        slot_requested_at="2026-07-25T12:00:00Z",
        runner_effective_limit=5.0,
    )

    assert format_queue_capacity_badge_value(4, explicit=False, multiplier=None) is None
    text = Text()
    assert append_agent_queue_badges(text, agent) is False
    assert "c4" not in text.plain
