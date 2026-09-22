"""Oneshot row unit tests: glyphs, chips, divider label, and ages.

These exercise the pure ``_format_bgcmd_option`` / ``_oneshot_chip`` /
``_oneshot_age`` helpers directly instead of driving the widget. See
``_bgcmd_list_formatters_helpers.py`` for the full row-taxonomy
rationale pinned by the AXE-tab visual redesign plan.
"""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.widgets.bgcmd_list import (
    _DIVIDER_LABEL,
    _oneshot_age,
    _oneshot_chip,
    BgCmdList,
)
from tests.ace.tui.widgets._bgcmd_list_formatters_helpers import (
    _bg_info,
    _option_text,
    _styles_in,
)


def _oneshot_info(status: str, **fields: object) -> BackgroundCommandInfo:
    info = _bg_info("make lint")
    info.proc_id = "proc-1"
    info.status = status
    for name, value in fields.items():
        setattr(info, name, value)
    return info


def _row(info: BackgroundCommandInfo, *, running: bool) -> Text:
    option = BgCmdList()._format_bgcmd_option(
        slot=2, info=info, is_selected=False, is_running=running
    )
    return _option_text(option)


def test_oneshot_divider_names_the_oneshots_section() -> None:
    assert _DIVIDER_LABEL == "── oneshots ──"


def test_running_oneshot_row_shows_play_glyph_and_running_chip() -> None:
    info = _oneshot_info("running", started_at="2026-05-11T00:00:00")
    plain = _row(info, running=True).plain
    assert plain.startswith("▷ #2 make lint")
    assert "running" in plain


def test_successful_oneshot_row_shows_check_glyph_and_exit_zero_chip() -> None:
    info = _oneshot_info(
        "success",
        exit_code=0,
        finished_at="2026-05-11T00:00:05",
    )
    text = _row(info, running=False)
    assert text.plain.startswith("✓ #2 make lint")
    assert "exit 0" in text.plain
    assert text.plain.rstrip().endswith("ago")


def test_failed_oneshot_row_shows_cross_glyph_and_exit_code_chip() -> None:
    info = _oneshot_info(
        "error",
        exit_code=2,
        finished_at="2026-05-11T00:00:05",
    )
    text = _row(info, running=False)
    assert text.plain.startswith("✗ #2 make lint")
    assert "exit 2" in text.plain
    assert any("#D78787" in style for style in _styles_in(text))


def test_killed_oneshot_row_shows_cross_glyph_and_killed_chip() -> None:
    info = _oneshot_info("killed", exit_code=-15)
    text = _row(info, running=False)
    assert text.plain.startswith("✗ #2")
    assert "killed" in text.plain
    assert "exit -15" not in text.plain


def test_legacy_done_row_has_no_exit_code_to_show() -> None:
    info = _bg_info("old command")
    info.status = "done"
    text = _row(info, running=False)
    assert text.plain.startswith("✓ #2 old command")
    assert "done" in text.plain
    assert "exit" not in text.plain


def test_oneshot_chip_without_a_timestamp_omits_the_age() -> None:
    info = _oneshot_info("success", exit_code=0, finished_at=None)
    assert _oneshot_chip(info, False) is not None
    assert _oneshot_chip(info, False)[0] == "exit 0"  # type: ignore[index]
    assert _oneshot_chip(None, True) is None


def test_oneshot_age_formats_compact_units() -> None:
    from datetime import datetime

    now = datetime(2026, 5, 11, 1, 0, 0)
    assert _oneshot_age("2026-05-11T00:59:30", now=now) == "30s"
    assert _oneshot_age("2026-05-11T00:56:00", now=now) == "4m"
    assert _oneshot_age("2026-05-10T22:00:00", now=now) == "3h"
    assert _oneshot_age("2026-05-08T01:00:00", now=now) == "3d"
    # A clock-skewed future timestamp never renders a negative age.
    assert _oneshot_age("2026-05-11T02:00:00", now=now) == "0s"
    assert _oneshot_age(None) is None
    assert _oneshot_age("not a timestamp") is None


def test_oneshot_age_converts_offset_timestamps_to_the_configured_timezone() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 5, 11, 1, 0, 0)  # configured-timezone wall clock
    with patch("sase.ace.tui.widgets.bgcmd_list.get_timezone", return_value=UTC):
        assert _oneshot_age("2026-05-11T00:56:00Z", now=now) == "4m"
        assert _oneshot_age("2026-05-11T00:56:00+00:00", now=now) == "4m"


def test_oneshot_age_defaults_to_the_pinned_local_clock() -> None:
    from datetime import datetime

    with patch(
        "sase.ace.tui.widgets.bgcmd_list.local_now",
        return_value=datetime(2026, 5, 11, 1, 0, 0),
    ):
        assert _oneshot_age("2026-05-11T00:00:00") == "1h"
