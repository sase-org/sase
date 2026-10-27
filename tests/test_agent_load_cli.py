"""``sase agent load`` view model and CLI: screenshot, invalid, stale, over-limit."""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout

from rich.console import Console

from sase.agents.cli_load import (
    handle_agents_load,
    _render_load_view,
    _report_to_json_dict,
)
from sase.core.runner_slots import capacity_view
from tests._runner_slots_helpers import _always_live, _record
from tests.test_machine_capacity_report import _report_from_records


def _screenshot_view(**kwargs):
    return capacity_view(_report_from_records(_screenshot_records()), **kwargs)


def _screenshot_records():
    from tests.test_machine_capacity_report import _screenshot_records as records

    return records()


def test_screenshot_shape_view_matches_plan_lines() -> None:
    view = _screenshot_view(running_nodes=6)

    assert view.headline == "5 of 8 units in use · 3 headroom"
    assert view.limit_line == (
        "limit 8: ACE override since 1970-01-01, no expiry · config default 10"
    )
    assert view.running_line == "6 running nodes · 5 holding capacity · 1 holding 0"
    assert view.over_limit_note is None
    assert view.total_charged == 5.0
    assert view.admission_blocked is False
    assert view.accounting_unavailable is False

    kinds = {row.name: row.kind for row in view.holdings}
    assert kinds["worker-a"] == "worker"
    assert kinds["verify-a"] == "verify monitor"
    assert kinds["cutover"] == "wait monitor"
    assert view.idle_groups == ()
    assert view.queued == ()


def test_running_line_omitted_without_running_nodes() -> None:
    assert _screenshot_view().running_line is None


def test_riders_render_as_shared_with_holder() -> None:
    parent = _record("/sess", run_started=True, agent_session="s1")
    child = _record("/sess2", run_started=True, agent_session="s1")
    view = capacity_view(_report_from_records([parent, child]))

    assert [(row.name, row.holder_name) for row in view.riders] == [("sess2", "sess")]
    assert [row.name for row in view.holdings] == ["sess"]


def test_idle_groups_group_by_reason_and_truncate() -> None:
    records = [
        _record(f"/idle-{index:02d}", requested_at=None, run_started=False)
        for index in range(12)
    ]
    view = capacity_view(_report_from_records(records))

    assert [group.reason_code for group in view.idle_groups] == ["not_started"]
    (group,) = view.idle_groups
    assert group.count == 12
    assert group.truncated is True
    assert group.hidden == 2
    assert len(group.members) == 10


def test_queued_rows_carry_real_blockers() -> None:
    waiter = _record(
        "/waiter",
        requested_at="2026-07-12T12:01:00Z",
        wait_runners=2,
        wait_priority=10,
        queue_weight=1.0,
        queue_weight_explicit=True,
    )
    records = _screenshot_records() + [waiter]
    view = capacity_view(_report_from_records(records, configured=8, override=None))

    assert len(view.queued) == 1
    (row,) = view.queued
    assert "blocked by capacity" in row.blocker
    assert "budget 2" in row.blocker


def test_invalid_weight_is_blocked_never_free() -> None:
    bad = _record("/bad", run_started=True)
    assert bad.agent_meta is not None
    object.__setattr__(bad.agent_meta, "queue_weight_invalid", True)
    view = capacity_view(_report_from_records([*_screenshot_records(), bad]))

    assert view.admission_blocked is True
    assert view.total_charged == 5.0
    rendered = _render(view)
    assert "admission blocked" in rendered
    assert "not free capacity" in rendered


def test_stale_report_says_so() -> None:
    view = capacity_view(
        _report_from_records(_screenshot_records(), scan_current=False)
    )
    assert "stale (token changed)" in view.snapshot_line


def test_over_limit_note_names_budgets() -> None:
    waiter = _record(
        "/waiter",
        requested_at="2026-07-12T12:01:00Z",
        wait_runners=2,
        wait_priority=10,
        queue_weight=1.0,
        queue_weight_explicit=True,
    )
    view = capacity_view(
        _report_from_records(
            [*_screenshot_records(), waiter], configured=1, override=None
        )
    )

    assert "5 of 1 units in use · 4 over budget" in view.headline
    assert view.over_limit_note is not None
    assert "c2" in view.over_limit_note
    assert "no new work is admitted" in view.over_limit_note


def test_older_core_reports_accounting_unavailable() -> None:
    report = _report_from_records(_screenshot_records())
    object.__setattr__(report, "accounting_available", False)
    object.__setattr__(report, "accounting", ())
    view = capacity_view(report)

    assert view.accounting_unavailable is True
    assert "too old" in _render(view)


def test_json_shape_carries_report_provenance_and_metadata() -> None:
    payload = _report_to_json_dict(_report_from_records(_screenshot_records()))

    assert payload["machine"] == "athena"
    assert payload["occupied_capacity"] == 5.0
    assert payload["effective_limit"] == 8.0
    assert payload["limit"]["configured_limit"] == 10
    assert payload["limit"]["temporary_override"]["limit"] == 8
    assert payload["limit"]["temporary_override"]["source"] == "ace"
    assert len(payload["accounting"]) == 6
    assert len(payload["claims"]) == 6
    assert payload["scan_current"] is True
    assert payload["accounting_valid"] is True
    assert payload["accounting_available"] is True
    assert len(payload["record_inputs"]) == 6


def test_cli_json_flag_emits_exact_report() -> None:
    report = _report_from_records(_screenshot_records())
    args = argparse.Namespace(json=True, rescan=False)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        handle_agents_load(args, report_fn=lambda force_rescan=False: report)
    payload = json.loads(buffer.getvalue())

    assert payload["occupied_capacity"] == 5.0
    assert payload["machine"] == "athena"
    assert len(payload["accounting"]) == 6


def test_cli_rescan_flag_reaches_report() -> None:
    seen: dict[str, bool] = {}
    report = _report_from_records(_screenshot_records())

    def report_fn(*, force_rescan: bool = False):
        seen["force_rescan"] = force_rescan
        return report

    with redirect_stdout(io.StringIO()):
        handle_agents_load(
            argparse.Namespace(json=True, rescan=True), report_fn=report_fn
        )
    assert seen["force_rescan"] is True


def test_cli_pretty_output_has_all_sections() -> None:
    report = _report_from_records(_screenshot_records())
    view = capacity_view(report, running_nodes=6)
    rendered = _render(view)

    assert "5 of 8 units in use" in rendered
    assert "Holding capacity" in rendered
    assert "verify monitor" in rendered
    assert "wait monitor" in rendered
    assert "Queued for capacity: none" in rendered
    assert "sase agent load -j" in rendered


def _render(view) -> str:
    buffer = io.StringIO()
    _render_load_view(view, machine="athena", console=Console(file=buffer, width=120))
    return buffer.getvalue()
