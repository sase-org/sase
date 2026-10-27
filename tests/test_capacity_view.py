"""Tiered capacity view: verdict, groups, durations, limit info, and gauge."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sase.config.runner_limit_override import (
    EffectiveRunnerLimitSnapshot,
    TemporaryRunnerLimitOverride,
)
from sase.core.agent_scan_wire import AgentSessionTurnWire
from sase.core.runner_slots import (
    capacity_gauge_cells,
    capacity_view,
    format_capacity_duration,
    machine_capacity_report_from_records,
)
from tests._runner_slots_helpers import _always_live, _live_unless_stopped, _record
from tests.test_machine_capacity_report import (
    _report_from_records,
    _screenshot_records,
)

_NOW = datetime(2026, 7, 12, 14, 0, tzinfo=UTC).timestamp()


def _view(records: list[Any], **kwargs: Any) -> Any:
    now = kwargs.pop("now", _NOW)
    running_nodes = kwargs.pop("running_nodes", None)
    report = _report_from_records(records, now=now, **kwargs)
    return capacity_view(report, running_nodes=running_nodes, now=now)


def _set(report: Any, **fields: Any) -> Any:
    for name, value in fields.items():
        object.__setattr__(report, name, value)
    return report


def _gate_record(path: str) -> Any:
    record = _record(
        path, run_started=True, agent_session="g", agent_session_role="gate"
    )
    assert record.agent_meta is not None
    object.__setattr__(
        record.agent_meta,
        "agent_session_turn",
        AgentSessionTurnWire(kind="gate", id="g1", state="pending"),
    )
    return record


def _waiter(
    path: str,
    *,
    weight: float = 1.0,
    budget: int = 8,
    priority: int = 10,
) -> Any:
    return _record(
        path,
        requested_at="2026-07-12T13:00:00Z",
        wait_runners=budget,
        wait_priority=priority,
        queue_weight=weight,
        queue_weight_explicit=True,
    )


def test_verdict_unknown_when_accounting_unavailable() -> None:
    report = _set(
        _report_from_records(_screenshot_records(), now=_NOW),
        accounting_available=False,
        accounting=(),
    )
    verdict = capacity_view(report).verdict
    assert verdict is not None
    assert verdict.tone == "unknown"
    assert verdict.title == "Holder accounting unavailable — totals only"
    assert verdict.detail == ("This sase-core build cannot explain individual holders.")


def test_verdict_blocked_when_accounting_invalid() -> None:
    bad = _record("/bad", run_started=True)
    assert bad.agent_meta is not None
    object.__setattr__(bad.agent_meta, "queue_weight_invalid", True)
    verdict = _view([*_screenshot_records(), bad], configured=8, override=None).verdict
    assert verdict is not None
    assert verdict.tone == "blocked"
    assert verdict.title == "Admission blocked — capacity accounting is invalid"
    assert verdict.detail == (
        "5 is a known subtotal, not free capacity · see Needs attention"
    )


def test_verdict_over_budget_uses_per_launch_clause() -> None:
    waiter = _waiter("/waiter", budget=2)
    view = _view([*_screenshot_records(), waiter], configured=1, override=None)
    assert view.verdict is not None
    assert view.verdict.tone == "over"
    assert view.verdict.title == (
        "Over budget by 4 — no new work starts until load drops"
    )
    assert view.verdict.detail is not None
    assert "c2" in view.verdict.detail
    assert view.verdict.detail.startswith("per-launch budgets in play:")


def test_verdict_over_budget_without_authored_budgets() -> None:
    view = _view(_screenshot_records(), configured=1, override=None)
    assert view.verdict is not None
    assert view.verdict.detail == (
        "admitted under per-launch %queue(capacity=N) budgets"
    )


def test_verdict_full_without_queue() -> None:
    view = _view(_screenshot_records(), configured=5, override=None)
    assert view.verdict is not None
    assert view.verdict.tone == "full"
    assert view.verdict.title == "Full — all 5 units in use"
    assert view.verdict.detail == "The next launch will queue until a unit frees up."


def test_verdict_full_with_queue_summary() -> None:
    view = _view(
        [*_screenshot_records(), _waiter("/waiter", budget=2)],
        configured=5,
        override=None,
    )
    assert view.verdict is not None
    assert view.verdict.tone == "full"
    assert view.verdict.detail is not None
    assert view.verdict.detail.startswith("1 queued · next up #1 waiter:")
    assert "blocked by capacity" in view.verdict.detail


def test_verdict_tight_fractional_free() -> None:
    report = _set(
        _report_from_records(
            _screenshot_records(), now=_NOW, configured=8, override=None
        ),
        occupied_capacity=5.0,
        effective_limit=5.5,
        over_limit=False,
    )
    verdict = capacity_view(report).verdict
    assert verdict is not None
    assert verdict.tone == "tight"
    assert verdict.title == "0.5 unit free — a default-weight agent would queue"
    assert verdict.detail is None


def test_verdict_ok_plural_and_singular() -> None:
    plural = _view(_screenshot_records(), configured=8, override=None)
    assert plural.verdict is not None
    assert plural.verdict.tone == "ok"
    assert plural.verdict.title == (
        "3 units free — room for 3 more default-weight agents"
    )
    assert plural.verdict.detail is None

    report = _set(
        _report_from_records(
            _screenshot_records(), now=_NOW, configured=8, override=None
        ),
        occupied_capacity=7.0,
        effective_limit=8.0,
        over_limit=False,
    )
    singular = capacity_view(report).verdict
    assert singular is not None
    assert singular.title == "1 unit free — room for 1 more default-weight agent"

    fractional = _set(
        _report_from_records(
            _screenshot_records(), now=_NOW, configured=8, override=None
        ),
        occupied_capacity=6.5,
        effective_limit=8.0,
        over_limit=False,
    )
    mixed = capacity_view(fractional).verdict
    assert mixed is not None
    assert mixed.title == "1.5 units free — room for 1 more default-weight agent"


def test_verdict_ok_with_queue_despite_free_room() -> None:
    view = _view(
        [_waiter("/heavy", weight=20.0, budget=8)],
        configured=8,
        override=None,
    )
    assert view.verdict is not None
    assert view.verdict.tone == "ok"
    assert view.verdict.detail is not None
    assert view.verdict.detail.startswith("1 still queued · #1 heavy:")
    assert "never fits" in view.verdict.detail


def test_unknown_holder_does_not_fall_through_to_not_started() -> None:
    report = _report_from_records(
        [_record("/ghost", requested_at=None, run_started=False)], now=_NOW
    )
    accounting = [dict(entry) for entry in report.accounting]
    accounting[0]["state"] = "unknown"
    accounting[0].pop("reason_code", None)
    _set(report, accounting=tuple(accounting))
    view = capacity_view(report)
    assert [group.reason_code for group in view.attention_groups] == ["unknown_holder"]
    assert view.attention_groups[0].reason_label == "claim holder unknown"
    assert view.waiting_groups == ()


def test_tier_assignment_for_every_reason_and_unrecognized_fallback() -> None:
    records = [
        _record("/wait-start"),
        _record("/question", run_started=True, pending_question=True),
        _gate_record("/gate"),
        _record("/zero", queue_weight=0.0, queue_weight_explicit=True),
        _record("/dead", run_started=True, stopped_at="2026-07-12T13:00:00Z"),
        _record("/done", run_started=True, done=True, pid=0),
        _record("/hidden", run_started=True, appears_as_agent=False),
        _record(
            "/nopid",
            run_started=True,
            pid=None,
            monitor_id="m",
            agent_session="s",
            agent_session_role="monitor",
        ),
    ]
    bad = _record("/invalid", run_started=True)
    assert bad.agent_meta is not None
    object.__setattr__(bad.agent_meta, "queue_weight_invalid", True)
    view = _view(
        [*records, bad],
        is_live=_live_unless_stopped,
        configured=8,
        override=None,
    )
    waiting = {group.reason_code: group for group in view.waiting_groups}
    inactive = {group.reason_code: group for group in view.inactive_groups}
    attention = {group.reason_code: group for group in view.attention_groups}
    assert waiting["not_started"].reason_label == "waiting to start"
    assert waiting["pending_question"].reason_label == "waiting on a question"
    assert waiting["pending_gate"].reason_label == "waiting on a gate"
    assert waiting["explicit_zero_weight"].reason_label == "zero weight"
    assert inactive["not_live"].reason_label == "not live"
    assert inactive["done"].reason_label == "done"
    assert inactive["not_agent_record"].reason_label == "not agent records"
    assert attention["no_pid"].reason_label == "no process evidence"
    assert attention["invalid_weight"].reason_label == "invalid weight"
    assert waiting["not_started"].explanation.startswith("Live, but its run")
    assert len(attention["no_pid"].members) == attention["no_pid"].count

    report = _report_from_records([_record("/x")], now=_NOW)
    extra = dict(report.accounting[0])
    extra["artifact_dir"] = "/other"
    extra["agent_name"] = "other"
    extra["reason_code"] = "brand_new_code"
    extra["state"] = "not_holding"
    _set(report, accounting=(*report.accounting, extra))
    other = capacity_view(report)
    (group,) = [
        item for item in other.waiting_groups if item.reason_code == "brand_new_code"
    ]
    assert group.reason_label == "brand new code"
    assert group.explanation == "Holds no capacity (reason: brand_new_code)."
    assert group.tier == "waiting"


def test_waiting_groups_keep_complete_membership() -> None:
    records = [_record(f"/idle-{index:02d}") for index in range(12)]
    view = _view(records)
    (waiting,) = view.waiting_groups
    assert waiting.reason_label == "waiting to start"
    assert waiting.count == 12
    assert len(waiting.members) == 12
    assert len(waiting.member_artifact_dirs) == 12


def test_charged_zero_weight_split_sort_and_riders() -> None:
    heavy = _record(
        "/heavy",
        run_started=True,
        queue_weight=2.0,
        queue_weight_explicit=True,
        name="heavy",
    )
    assert heavy.agent_meta is not None
    object.__setattr__(heavy.agent_meta, "run_started_at", "2026-07-12T10:00:00+00:00")
    light = _record("/light", run_started=True, name="light")
    assert light.agent_meta is not None
    object.__setattr__(light.agent_meta, "run_started_at", "2026-07-12T11:00:00+00:00")
    zero = _record(
        "/cutover",
        agent_session="cutover",
        agent_session_role="monitor",
        monitor_id="cutover-turn",
        queue_weight=0.0,
        queue_weight_explicit=True,
    )
    parent = _record("/sess", run_started=True, agent_session="s1")
    child = _record("/sess2", run_started=True, agent_session="s1")
    view = _view([heavy, light, zero, parent, child], configured=10, override=None)
    assert [row.name for row in view.charged] == ["heavy", "light", "sess"]
    assert [row.charged_weight for row in view.charged] == [2.0, 1.0, 1.0]
    assert view.charged[0].running_seconds == 4 * 3600
    assert view.charged[0].project_key == "proj"
    assert view.charged[2].rider_names == ("sess2",)
    assert [row.name for row in view.zero_weight] == ["cutover"]
    (rider,) = view.riders
    assert rider.holder_artifact_dir == "/sess"
    assert rider.project_key == "proj"
    assert rider.running_seconds == 2 * 3600


def test_queue_tones_blockers_and_waiting_seconds() -> None:
    capacity = _view(
        [*_screenshot_records(), _waiter("/waiter", budget=2)],
        configured=8,
        override=None,
    )
    (row,) = capacity.queued
    assert row.tone == "capacity"
    assert row.blockers == (row.blocker,)
    assert "blocked by capacity" in row.blocker
    assert row.waiting_seconds == 3600.0
    assert row.project_key == "proj"

    never = _view(
        [_waiter("/heavy", weight=20.0, budget=8)], configured=8, override=None
    )
    assert never.queued[0].tone == "never_fits"
    assert "never fits" in never.queued[0].blockers[0]

    ready = _view([_waiter("/ready", budget=8)], configured=8, override=None)
    assert ready.queued[0].tone == "ready"
    assert ready.queued[0].blockers == ()
    assert ready.queued[0].blocker == "eligible · fits within budget"

    report = _report_from_records(
        [_waiter("/held", budget=8)], now=_NOW, configured=8, override=None
    )
    waiters = [dict(report.waiters[0])]
    waiters[0]["eligible"] = False
    waiters[0]["blockers"] = [
        {"code": "hold-barrier", "held_by": "sase-1ob", "hold_expires_at": _NOW + 60}
    ]
    _set(report, waiters=tuple(waiters))
    held = capacity_view(report, now=_NOW).queued[0]
    assert held.tone == "held"
    assert held.blockers[0].startswith("held by sase-1ob · until ")

    deferred_waiters = [dict(waiters[0])]
    deferred_waiters[0]["blockers"] = [{"code": "deference-window"}]
    _set(report, waiters=tuple(deferred_waiters))
    deferred = capacity_view(report, now=_NOW).queued[0]
    assert deferred.tone == "deferred"
    assert deferred.blockers == ("deferred · a better-priority waiter arrived first",)

    other_waiters = [dict(waiters[0])]
    other_waiters[0]["blockers"] = [{"code": "custom-block", "message": "nope."}]
    _set(report, waiters=tuple(other_waiters))
    other = capacity_view(report, now=_NOW).queued[0]
    assert other.tone == "other"
    assert other.blockers == ("nope",)


def test_limit_info_override_config_expired_and_long_lived() -> None:
    short = TemporaryRunnerLimitOverride(
        version=1,
        limit=8,
        created_at=_NOW - 100.0,
        expires_at=None,
        source="ace",
    )
    short_report = machine_capacity_report_from_records(
        _screenshot_records(),
        _always_live,
        now=_NOW,
        token="tok",
        scanned_at=_NOW,
        scan_current=True,
        limit=EffectiveRunnerLimitSnapshot(
            configured_limit=10, temporary_override=short, captured_at=_NOW
        ),
    )
    info = capacity_view(short_report, now=_NOW).limit_info
    assert info is not None
    assert info.effective == 8.0
    assert info.configured == 10.0
    assert info.override_source == "ACE"
    assert info.override_created_at == _NOW - 100.0
    assert info.override_expires_at is None
    assert info.override_long_lived is False
    assert info.override_age_seconds == 100.0

    config = _view(_screenshot_records(), configured=10, override=None)
    assert config.limit_info is not None
    assert config.limit_info.override_source is None
    assert config.limit_info.configured == 10.0
    assert config.limit_info.effective == 10.0

    expired = TemporaryRunnerLimitOverride(
        version=1,
        limit=8,
        created_at=_NOW - 100.0,
        expires_at=_NOW - 1.0,
        source="ace",
    )
    report = machine_capacity_report_from_records(
        _screenshot_records(),
        _always_live,
        now=_NOW,
        token="tok",
        scanned_at=_NOW,
        scan_current=True,
        limit=EffectiveRunnerLimitSnapshot(
            configured_limit=10, temporary_override=expired, captured_at=_NOW
        ),
    )
    expired_info = capacity_view(report).limit_info
    assert expired_info is not None
    assert expired_info.override_source is None
    assert expired_info.effective == 10.0

    long_lived = TemporaryRunnerLimitOverride(
        version=1,
        limit=8,
        created_at=_NOW - 44 * 24 * 3600,
        expires_at=None,
        source="ace",
    )
    aged = machine_capacity_report_from_records(
        _screenshot_records(),
        _always_live,
        now=_NOW,
        token="tok",
        scanned_at=_NOW,
        scan_current=True,
        limit=EffectiveRunnerLimitSnapshot(
            configured_limit=10, temporary_override=long_lived, captured_at=_NOW
        ),
    )
    aged_info = capacity_view(aged).limit_info
    assert aged_info is not None
    assert aged_info.override_long_lived is True
    assert aged_info.override_age_seconds == 44 * 24 * 3600


def test_format_capacity_duration_clamps_and_buckets() -> None:
    assert format_capacity_duration(None) == "—"
    assert format_capacity_duration(-12.0) == "0s"
    assert format_capacity_duration(45.0) == "45s"
    assert format_capacity_duration(59.9) == "59s"
    assert format_capacity_duration(60.0) == "1m"
    assert format_capacity_duration(4 * 60.0) == "4m"
    assert format_capacity_duration(3600.0 + 6 * 60.0) == "1h06m"
    assert format_capacity_duration(3 * 86400.0 + 4 * 3600.0) == "3d04h"


def test_gauge_slot_mode_owners_and_beyond() -> None:
    heavy = _record(
        "/heavy",
        run_started=True,
        queue_weight=2.0,
        queue_weight_explicit=True,
        name="heavy",
    )
    half = _record(
        "/half",
        run_started=True,
        queue_weight=0.5,
        queue_weight_explicit=True,
        name="half",
    )
    view = _view([heavy, half], configured=8, override=None)
    cells = capacity_gauge_cells(view, 24)
    assert len(cells) == 24
    assert view.occupied == 2.5
    used = [cell for cell in cells if cell.kind == "used"]
    free = [cell for cell in cells if cell.kind == "free"]
    gaps = [cell for cell in cells if cell.kind == "gap"]
    beyond = [cell for cell in cells if cell.kind == "beyond"]
    assert {cell.char for cell in used} == {"█"}
    assert {cell.char for cell in free} == {"░"}
    assert len(gaps) == 7
    assert len(beyond) == 1
    assert cells[0].owner == 0 and cells[3].owner == 0
    assert cells[6].kind == "used" and cells[6].owner == 1
    assert cells[7].kind == "free" and cells[7].owner is None
    assert all(
        cell.owner is None for cell in cells if cell.kind in {"free", "gap", "beyond"}
    )


def test_gauge_width_below_eight_and_non_finite_is_empty() -> None:
    view = _view(_screenshot_records(), configured=8, override=None)
    assert capacity_gauge_cells(view, 7) == ()
    object.__setattr__(view, "limit", float("nan"))
    assert capacity_gauge_cells(view, 24) == ()


def test_gauge_continuous_mode_and_over_limit_marker() -> None:
    view = _view(_screenshot_records(), configured=8, override=None)
    cells = capacity_gauge_cells(view, 8)
    assert len(cells) == 8
    assert "gap" not in {cell.kind for cell in cells}
    assert {cell.kind for cell in cells} <= {"used", "free", "unknown", "beyond"}

    over = _view(_screenshot_records(), configured=1, override=None)
    cells = capacity_gauge_cells(over, 8)
    assert len(cells) == 8
    kinds = [cell.kind for cell in cells]
    assert "limit" in kinds
    assert "over" in kinds
    marker = next(cell for cell in cells if cell.kind == "limit")
    assert marker.char == "┃"
    assert marker.owner is None
    assert "gap" not in kinds
    assert any(cell.kind == "used" for cell in cells)


def test_gauge_slot_mode_over_limit_replaces_the_gap_with_a_marker() -> None:
    view = _view(_screenshot_records(), configured=1, override=None)
    cells = capacity_gauge_cells(view, 24)
    kinds = [cell.kind for cell in cells]
    assert "limit" in kinds
    assert "over" in kinds
    assert "gap" in kinds
    marker = next(cell for cell in cells if cell.kind == "limit")
    assert marker.char == "┃"


def test_gauge_invalid_accounting_uses_unknown_without_owners() -> None:
    bad = _record("/bad", run_started=True)
    assert bad.agent_meta is not None
    object.__setattr__(bad.agent_meta, "queue_weight_invalid", True)
    view = _view([*_screenshot_records(), bad], configured=8, override=None)
    cells = capacity_gauge_cells(view, 24)
    assert any(cell.kind == "unknown" for cell in cells)
    assert all(cell.char == "╱" for cell in cells if cell.kind == "unknown")
    assert all(cell.owner is None for cell in cells)


def test_legacy_screenshot_fields_are_unchanged() -> None:
    view = _view(_screenshot_records(), running_nodes=6, now=2_000.0)
    assert view.headline == "5 of 8 units in use · 3 headroom"
    assert view.limit_line == (
        "limit 8: ACE override since 1970-01-01, no expiry · config default 10"
    )
    assert view.running_line == "6 running nodes · 5 holding capacity · 1 holding 0"
    assert view.over_limit_note is None
    assert view.total_charged == 5.0
    assert view.waiting_groups == ()
    assert view.queued == ()
    assert view.occupied == 5.0
    assert view.limit == 8.0
    assert view.free == 3.0
    assert view.scan_current is True
