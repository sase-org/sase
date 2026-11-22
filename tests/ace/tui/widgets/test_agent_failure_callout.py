"""NEEDS ATTENTION callout rendering and tribe cause-line reuse."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models.failure_focus import (
    FailureFocus,
    _FailureRowFocus,
    _NotAdoptedHandoffFocus,
    failure_cause_summary,
    failure_has_structured_causes,
)
from sase.ace.tui.widgets.prompt_panel._agent_failure_callout import (
    append_failure_callout,
    format_failure_where_clan,
    format_failure_where_session,
)


def _full_focus() -> FailureFocus:
    return FailureFocus(
        member_label=".8",
        failed_row=_FailureRowFocus(
            name="research.8--1",
            stop_time=datetime(2026, 11, 22, 0, 0, 32),
            duration_seconds=512.0,
        ),
        finalizer_chip="⊛✗ commit",
        not_adopted=_NotAdoptedHandoffFocus(
            name="research.8--mon-0",
            kind="monitor",
            starter_name="research.8--1",
        ),
        blocked=(".land",),
        extra_failed=0,
        finalizer_chip_style="bold #FF5F5F",
    )


def test_cause_summary_shared_across_panels() -> None:
    focus = _full_focus()
    summary = failure_cause_summary(focus)
    assert "⊛✗ commit" in summary
    assert "never ran" in summary
    assert "blocks .land" in summary


def test_callout_gates_on_structured_causes() -> None:
    assert failure_has_structured_causes(_full_focus()) is True
    simple = FailureFocus(
        member_label=".second",
        failed_row=_FailureRowFocus(
            name="research.second",
            stop_time=datetime(2026, 7, 17, 12, 1, 45),
            duration_seconds=45.0,
        ),
        finalizer_chip=None,
        not_adopted=None,
        blocked=(),
        extra_failed=0,
    )
    assert failure_has_structured_causes(simple) is False


def test_full_callout_has_six_lines_and_cli_hint() -> None:
    text = Text()
    append_failure_callout(
        text, _full_focus(), where="wave 3 stopped at .8", jump_number="07"
    )
    lines = [line for line in text.plain.splitlines() if line.strip()]
    assert len(lines) == 6
    assert lines[0] == "┃ ✗ NEEDS ATTENTION · wave 3 stopped at .8"
    assert "sase agent readopt research.8--1" in text.plain
    assert "jump 07" in text.plain
    assert "R retry" in text.plain
    assert "x dismiss" in text.plain


def test_minimal_callout_points_to_error() -> None:
    focus = FailureFocus(
        member_label="--1",
        failed_row=_FailureRowFocus(
            name="family--1",
            stop_time=datetime(2026, 11, 22, 12, 8, 32),
            duration_seconds=60.0,
        ),
        finalizer_chip=None,
        not_adopted=None,
        blocked=(),
        extra_failed=0,
    )
    text = Text()
    append_failure_callout(
        text, focus, where=format_failure_where_session(focus), jump_number=None
    )
    assert "see ERROR below for details" in text.plain
    assert "turn --1 failed" in text.plain


def test_where_helpers() -> None:
    focus = _full_focus()
    assert format_failure_where_session(focus) == "turn .8 failed"

    class _Waves:
        waves: tuple = ()

    assert format_failure_where_clan(_Waves(), focus) == "stopped at .8"
