"""Occupancy marks on Running rows and the charged Capacity detail line.

Marks read the per-record accounting attached to each row: ``▰N`` for what a
Running-bucket row is charged now (``▰0`` for an explicit zero claim), ``▱``
for a Running row holding nothing, and ``▱?`` when the charge is unknown.
"""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.ace.tui.widgets._agent_list_render_cache import agent_render_key
from sase.ace.tui.widgets._queue_weight_badge import _capacity_mark_text
from sase.ace.tui.widgets.prompt_panel._agent_display_header_metadata_identity import (
    append_identity_fields,
)

from .agent_list_runtime_helpers import agent as make_agent


def _holding_row(
    status: str = "RUNNING",
    *,
    charged: float | None = 1.0,
    source: str = "default",
    reason: str | None = None,
    role_suffix: str | None = None,
    raw_suffix: str = "20260425143000",
    cl_name: str = "demo",
) -> object:
    row = make_agent(
        status=status, role_suffix=role_suffix, raw_suffix=raw_suffix, cl_name=cl_name
    )
    row.capacity_state = "holding"
    row.capacity_charged = charged
    row.capacity_weight_source = source
    row.capacity_reason = reason
    row.capacity_accounting_available = True
    return row


def test_holding_mark_shows_charged_number_before_status() -> None:
    row = _holding_row()

    left, _, _ = format_agent_option(row, 0, is_selected=False)

    assert _capacity_mark_text(row) == "▰1"
    assert "▰1" in left.plain
    assert left.plain.index("▰1") < left.plain.index("(RUNNING)")


def test_explicit_zero_mark_shows_zero() -> None:
    row = _holding_row(
        status="WAITING CUTOVER",
        charged=0.0,
        source="explicit_zero",
        reason="explicit_zero_weight",
        role_suffix="--mon",
        cl_name="demo--mon",
    )
    row.agent_session_role = "monitor"
    assert row.is_monitor

    assert _capacity_mark_text(row) == "▰0"


def test_rider_and_idle_rows_show_hollow_mark() -> None:
    rider = make_agent(status="RUNNING")
    rider.capacity_state = "riding_claim"
    rider.capacity_charged = 0.0
    rider.capacity_accounting_available = True
    idle = make_agent(status="RUNNING", raw_suffix="20260425143100")
    idle.capacity_state = "not_holding"
    idle.capacity_reason = "not_started"
    idle.capacity_accounting_available = True

    assert _capacity_mark_text(rider) == "▱"
    assert _capacity_mark_text(idle) == "▱"


def test_unknown_rows_show_hollow_question_mark() -> None:
    row = make_agent(status="RUNNING")
    row.capacity_state = "unknown"
    row.capacity_reason = "no_pid"
    row.capacity_accounting_available = True

    assert _capacity_mark_text(row) == "▱?"


def test_non_running_and_unapplied_rows_show_no_mark() -> None:
    done = make_agent(status="DONE", raw_suffix="20260425143200")
    done.capacity_state = "not_holding"
    done.capacity_reason = "done"
    done.capacity_accounting_available = True
    queued = make_agent(status="QUEUED", raw_suffix="20260425143300")
    queued.capacity_state = "waiting"
    queued.capacity_accounting_available = True
    fresh = make_agent(status="RUNNING", raw_suffix="20260425143400")

    assert _capacity_mark_text(done) is None
    assert _capacity_mark_text(queued) is None
    assert _capacity_mark_text(fresh) is None


def test_clan_container_mark_follows_count_chip() -> None:
    container = make_agent(status="RUNNING", raw_suffix="clan-root", cl_name="research")
    container.is_clan_container = True
    container.agent_clan = "research"
    container.agent_clan_generation = "gen-1"
    container.refresh_raw_presented_agent_name()
    lane = make_agent(status="RUNNING", raw_suffix="lane", cl_name="research.a")
    lane.agent_clan = "research"
    lane.agent_clan_generation = "gen-1"
    container.runtime_children = [lane]
    container.capacity_state = "holding"
    container.capacity_charged = 2.0
    container.capacity_accounting_available = True

    left, _, _ = format_agent_option(
        container, 0, is_selected=False, now=datetime(2026, 7, 19, 9, 50, 0)
    )

    assert _capacity_mark_text(container) == "▰2"
    assert "▰2" in left.plain
    assert left.plain.index("▰2") > left.plain.index("]")


def test_render_key_changes_with_capacity_fields() -> None:
    first = _holding_row()
    second = _holding_row()
    second.capacity_charged = 2.0

    key_kwargs: dict[str, object] = {
        "is_selected": False,
        "fold_annotation": "",
        "is_expanded": False,
        "is_marked": False,
    }
    twin = _holding_row()
    assert agent_render_key(first, 0, **key_kwargs) == agent_render_key(
        twin, 0, **key_kwargs
    )
    assert agent_render_key(first, 0, **key_kwargs) != agent_render_key(
        second, 0, **key_kwargs
    )


def _identity_text(row: object) -> str:
    text = Text()
    append_identity_fields(text, row, None, lambda _agent: None, None)
    return text.plain


def test_detail_line_for_verify_monitor_is_never_suppressed() -> None:
    row = _holding_row(status="TESTING", role_suffix="--mon", cl_name="demo--mon")
    row.agent_session_role = "monitor"
    row.agent_name = "demo--mon"
    assert row.is_monitor

    assert "Capacity: 1 (verify monitor, session demo--mon)" in _identity_text(row)


def test_detail_line_for_explicit_zero_wait_monitor() -> None:
    row = _holding_row(
        status="WAITING CUTOVER",
        charged=0.0,
        source="explicit_zero",
        reason="explicit_zero_weight",
        role_suffix="--mon",
        cl_name="demo--mon",
    )
    row.agent_session_role = "monitor"
    row.agent_name = "demo--mon"

    assert "Capacity: 0 (wait monitor, explicit w0, session demo--mon)" in (
        _identity_text(row)
    )


def test_detail_line_for_rider_and_idle_and_unknown() -> None:
    rider = make_agent(status="RUNNING")
    rider.agent_name = "rider"
    rider.refresh_raw_presented_agent_name()
    rider.capacity_state = "riding_claim"
    rider.capacity_claim_holder_dir = "/tmp/holder"
    rider.capacity_claim_holder_name = "holder"
    rider.capacity_accounting_available = True

    idle = make_agent(status="RUNNING", raw_suffix="20260425143500")
    idle.agent_name = "idle"
    idle.refresh_raw_presented_agent_name()
    idle.capacity_state = "not_holding"
    idle.capacity_reason = "not_started"
    idle.capacity_accounting_available = True

    unknown = make_agent(status="RUNNING", raw_suffix="20260425143600")
    unknown.agent_name = "unknown"
    unknown.refresh_raw_presented_agent_name()
    unknown.capacity_state = "unknown"
    unknown.capacity_reason = "unavailable"
    unknown.capacity_accounting_available = False

    assert "Capacity: shared with holder" in _identity_text(rider)
    assert "Capacity: none (not started — waiting on deps)" in _identity_text(idle)
    assert "Capacity: ? (accounting unavailable)" in _identity_text(unknown)


def test_detail_line_for_clan_container() -> None:
    container = make_agent(status="RUNNING", raw_suffix="clan-root", cl_name="research")
    container.is_clan_container = True
    container.agent_clan = "research"
    container.agent_clan_generation = "gen-1"
    container.refresh_raw_presented_agent_name()
    container.capacity_state = "holding"
    container.capacity_charged = 2.0
    container.capacity_accounting_available = True

    assert "Capacity: 2 (clan)" in _identity_text(container)


def test_end_to_end_marks_from_authoritative_snapshot() -> None:
    holder = make_agent(status="RUNNING")
    holder.artifacts_dir = "/tmp/artifacts/ace-run/holder"
    snapshot = {
        "occupied_lanes": 1,
        "occupied_capacity": 1.0,
        "effective_limit": 8.0,
        "claims": [],
        "waiters": [],
        "accounting": [
            {
                "artifact_dir": holder.artifacts_dir,
                "project_name": "demo",
                "agent_name": "demo",
                "state": "holding",
                "charged_weight": 1.0,
                "effective_weight": 1.0,
                "weight_source": "default",
                "claim_owner_key": "owner-a",
                "claim_holder_artifact_dir": holder.artifacts_dir,
                "reason_code": None,
            }
        ],
    }

    refresh_runner_slot_context([holder], raw_snapshot=snapshot, report=None)

    left, _, _ = format_agent_option(holder, 0, is_selected=False)
    assert "▰1" in left.plain
