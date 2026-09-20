"""Collection gating and display-outcome bookkeeping of the Agents paint log."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agents._paint_log import record_agents_paint_frame
from sase.ace.tui.actions.agents._refresh_trace import (
    paint_log_active,
    record_agents_refresh_trace,
    take_display_outcome,
)


class _App:
    pass


@pytest.fixture(autouse=True)
def _trace_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_TUI_TRACE", raising=False)


def _record(app: _App, display_cost: str | None, fallback: str | None = None) -> None:
    record_agents_refresh_trace(
        app,
        stage="display",
        source="watcher",
        display_cost=display_cost,  # type: ignore[arg-type]
        fallback_reason=fallback,
    )


def test_paint_log_is_off_unless_a_collector_or_the_trace_flag_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _App()
    assert not paint_log_active(app)

    app._agents_paint_log = []  # type: ignore[attr-defined]
    assert paint_log_active(app)

    other = _App()
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    assert paint_log_active(other)


def test_disabled_paint_log_neither_accumulates_nor_captures() -> None:
    app = _App()

    _record(app, "display_full_rebuild", "stale_grouping_mode")
    record_agents_paint_frame(app, kind="full_rebuild")  # must not touch the app

    assert take_display_outcome(app) == (None, None)
    assert not hasattr(app, "_agents_paint_seq")


def test_display_outcome_reports_the_costliest_cost_and_first_fallback() -> None:
    app = _App()
    app._agents_paint_log = []  # type: ignore[attr-defined]

    _record(app, "row_patch")
    _record(app, "display_full_rebuild", "stale_grouping_mode")
    _record(app, "display_panel_rebuild", "panel_membership_change")
    _record(app, None)  # data-stage records carry no display cost

    assert take_display_outcome(app) == (
        "display_full_rebuild",
        "stale_grouping_mode",
    )


def test_taking_the_display_outcome_clears_it() -> None:
    app = _App()
    app._agents_paint_log = []  # type: ignore[attr-defined]
    _record(app, "row_patch")

    assert take_display_outcome(app) == ("row_patch", None)
    assert take_display_outcome(app) == (None, None)
