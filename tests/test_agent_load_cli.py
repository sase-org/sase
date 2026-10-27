"""``sase agent load`` view model and CLI: screenshot, invalid, stale, over-limit."""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout

from rich.console import Console

from sase.ace.tui.widgets._usage_indicator_palette import usage_rejected_style
from sase.agents.cli_load import (
    handle_agents_load,
    _attention_text,
    _diagnostics_panel,
    _gauge_text,
    _render_load_view,
    _report_to_json_dict,
    _waiting_text,
    _zero_weight_text,
)
from sase.core.runner_slots import capacity_view
from tests._runner_slots_helpers import _live_unless_stopped, _record
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

    kinds = {row.name: row.kind for row in view.charged}
    assert kinds["worker-a"] == "worker"
    assert kinds["verify-a"] == "verify monitor"
    assert [row.name for row in view.zero_weight] == ["cutover"]
    assert view.waiting_groups == ()
    assert view.queued == ()
    assert view.verdict is not None
    assert view.verdict.tone == "ok"


def test_running_line_omitted_without_running_nodes() -> None:
    assert _screenshot_view().running_line is None


def test_riders_render_as_shared_with_holder() -> None:
    parent = _record("/sess", run_started=True, agent_session="s1")
    child = _record("/sess2", run_started=True, agent_session="s1")
    view = capacity_view(_report_from_records([parent, child]))

    assert [(row.name, row.holder_name) for row in view.riders] == [("sess2", "sess")]
    assert [row.name for row in view.charged] == ["sess"]
    rendered = _render(view)
    assert "shares sess's claim" in rendered
    assert "Running at zero weight" in rendered


def test_waiting_groups_preview_ten_names_in_cli() -> None:
    records = [
        _record(f"/idle-{index:02d}", requested_at=None, run_started=False)
        for index in range(12)
    ]
    view = capacity_view(_report_from_records(records))

    assert [group.reason_code for group in view.waiting_groups] == ["not_started"]
    (group,) = view.waiting_groups
    assert group.count == 12
    assert len(group.members) == 12
    rendered = _render(view)
    compact = " ".join(rendered.split())
    assert "waiting to start (12):" in compact
    assert "idle-00" in compact
    assert "+2 more" in compact
    assert "idle-11" not in compact.split("+2 more")[0]


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
    assert row.artifact_dir.endswith("waiter")
    rendered = _render(view)
    assert "Queued for capacity (1)" in rendered
    assert "waiter" in rendered
    assert "blocked by capacity" in rendered


def test_invalid_weight_is_blocked_never_free() -> None:
    bad = _record("/bad", run_started=True)
    assert bad.agent_meta is not None
    object.__setattr__(bad.agent_meta, "queue_weight_invalid", True)
    view = capacity_view(_report_from_records([*_screenshot_records(), bad]))

    assert view.admission_blocked is True
    assert view.total_charged == 5.0
    rendered = _render(view)
    assert "Admission blocked" in rendered
    assert "not free capacity" in rendered
    assert "Needs attention" in rendered
    assert "? free" in rendered


def test_stale_report_says_so() -> None:
    view = capacity_view(
        _report_from_records(_screenshot_records(), scan_current=False)
    )
    assert view.scan_current is False
    rendered = _render(view)
    assert "records changed since scan" in rendered


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

    assert view.verdict is not None
    assert view.verdict.tone == "over"
    assert "c2" in (view.verdict.detail or "")
    rendered = _render(view)
    assert "Over budget by 4" in rendered
    assert "c2" in rendered
    assert "over" in rendered.lower()


def test_older_core_reports_accounting_unavailable() -> None:
    report = _report_from_records(_screenshot_records())
    object.__setattr__(report, "accounting_available", False)
    object.__setattr__(report, "accounting", ())
    view = capacity_view(report)

    assert view.accounting_unavailable is True
    rendered = _render(view)
    assert "totals only" in rendered
    assert "Using capacity" not in rendered


def test_inactive_records_are_counted_not_listed() -> None:
    records = [
        *_screenshot_records(),
        _record("/dead", run_started=True, stopped_at="2026-07-12T13:00:00Z"),
        _record("/done", run_started=True, done=True, pid=0),
        _record("/hidden", run_started=True, appears_as_agent=False),
    ]
    view = capacity_view(_report_from_records(records, is_live=_live_unless_stopped))
    rendered = _render(view)

    assert "Ignored 3 inactive records:" in rendered
    assert "1 not live" in rendered
    assert "1 not agent records" in rendered
    assert "1 done" in rendered
    assert "dead" not in rendered.split("Ignored")[0]
    assert "(sase agent load -j lists them)" in rendered


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

    assert "athena · 5 / 8 units in use · 3 free" in rendered
    assert "Using capacity (5 units · 5 agents)" in rendered
    assert "verify monitor" in rendered
    assert "Running at zero weight" in rendered
    assert "wait monitor" in rendered
    assert "Queued for capacity (0)" in rendered
    assert "sase agent load -j" in rendered
    assert view.verdict is not None
    assert view.verdict.title in rendered
    assert "█" in rendered or "░" in rendered


def _render(view) -> str:
    buffer = io.StringIO()
    _render_load_view(view, machine="athena", console=Console(file=buffer, width=120))
    return buffer.getvalue()


def _invalid_only_report():
    bad = _record("/bad", run_started=True, name="invalid-weight")
    assert bad.agent_meta is not None
    object.__setattr__(bad.agent_meta, "queue_weight_invalid", True)
    return _report_from_records([bad])


def test_invalid_only_empty_charged_is_unknown_not_free() -> None:
    view = capacity_view(_invalid_only_report())
    rendered = _render(view)

    assert "No known charged claims — free capacity is unknown" in rendered
    assert "all 8 units are free" not in rendered
    assert "Nothing holds capacity" not in rendered
    assert "Needs attention" in rendered
    assert "? free" in rendered


def test_valid_empty_charged_still_shows_all_free() -> None:
    view = capacity_view(
        _report_from_records([_record("/idle", requested_at=None, run_started=False)])
    )
    rendered = _render(view)

    assert "Nothing holds capacity — all 8 units are free" in rendered
    assert "free capacity is unknown" not in rendered


def test_cli_attention_zero_weight_and_waiting_keep_rich_spans() -> None:
    view = capacity_view(_report_from_records(_screenshot_records(), configured=8))
    zero = _zero_weight_text(view)
    assert zero is not None
    assert zero.spans
    assert any("dim" in str(span.style) for span in zero.spans)

    waiting_view = capacity_view(
        _report_from_records(
            [
                _record(f"/idle-{index:02d}", requested_at=None, run_started=False)
                for index in range(3)
            ]
        )
    )
    waiting = _waiting_text(waiting_view)
    assert waiting is not None
    assert waiting.spans
    assert any("bold" in str(span.style) for span in waiting.spans)

    blocked = capacity_view(_invalid_only_report())
    attention = _attention_text(blocked)
    assert attention is not None
    body = attention.renderable
    assert hasattr(body, "spans")
    assert body.spans
    assert any("yellow" in str(span.style) for span in body.spans)
    diagnostics = _diagnostics_panel(blocked)
    diag_body = diagnostics.renderable
    assert hasattr(diag_body, "spans")
    assert any("red" in str(span.style) for span in diag_body.spans)


def test_cli_blocked_gauge_styles_known_used_as_rejected() -> None:
    bad = _record("/bad", run_started=True)
    assert bad.agent_meta is not None
    object.__setattr__(bad.agent_meta, "queue_weight_invalid", True)
    view = capacity_view(_report_from_records([*_screenshot_records(), bad]))
    gauge = _gauge_text(view, width=32)
    assert gauge is not None
    rejected = usage_rejected_style(dark=True)
    used = [span for span in gauge.spans if "█" in gauge.plain[span.start : span.end]]
    assert used
    assert any(rejected in str(span.style) for span in used)
