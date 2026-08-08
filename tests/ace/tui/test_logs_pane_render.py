"""Pure rendering tests for the Admin Center Logs tab (no app required)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sase.core.time import parse_local, to_local
from sase.ace.tui.logs import log_sources
from sase.ace.tui.modals import logs_pane as lp
from sase.ace.tui.modals import logs_pane_render as lp_render
from sase.ace.tui.modals.logs_pane import (
    _CYAN,
    _GOLD,
    _styled_log_line,
    _render_log_detail,
)
from tests.ace.tui._logs_pane_helpers import log_dir as log_dir
from tests.ace.tui._logs_pane_helpers import LAUNCH_LOG_BODY, write_log


def _write_with_mtime(path: Path, text: str, epoch: float) -> None:
    path.write_text(text, encoding="utf-8")
    os.utime(path, (epoch, epoch))


def test_render_text_source_includes_header_and_body(log_dir: Path) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)
    source = next(s for s in log_sources() if s.id == "launch_failures")

    text = _render_log_detail(source).plain

    assert str(source.path) in text  # header path
    assert "single launch failure: alpha" in text
    assert "RuntimeError: boom" in text


def test_render_empty_source_shows_friendly_empty_state(log_dir: Path) -> None:
    source = next(s for s in log_sources() if s.id == "launch_failures")

    text = _render_log_detail(source).plain

    assert "No launch failures logged" in text


@pytest.mark.parametrize(
    "num_bytes, expected",
    [
        (0, "0B"),
        (999, "999B"),
        (1000, "1.0K"),
        (1023, "1.0K"),
        (13107, "13K"),
        (619315, "605K"),
        (1048000, "1.0M"),
        (1782579, "1.7M"),
        (2097152, "2.0M"),
    ],
)
def test_format_size_compact_stays_within_four_cells(
    num_bytes: int, expected: str
) -> None:
    result = lp_render.format_size_compact(num_bytes)

    assert result == expected
    assert len(result) <= 4


_AGE_NOW_EPOCH = 1782000000.0


def _age_now() -> datetime:
    """Naive configured-tz "now" reference for :data:`_AGE_NOW_EPOCH`.

    Resolved per test rather than at import: the autouse
    ``_pin_configured_timezone`` fixture has not run at collection time, so an
    import-time reference would be built in the *host* timezone and drift from
    the pinned one by the offset between them (Eastern on a dev machine, UTC on
    CI).
    """
    parsed = parse_local(_AGE_NOW_EPOCH)
    assert parsed is not None
    return to_local(parsed)


@pytest.mark.parametrize(
    "delta_seconds, expected",
    [
        (-5, "now"),  # future mtime (clock skew) clamps to "now"
        (0, "now"),
        (59, "now"),
        (60, "1m ago"),  # 59s/60s boundary
        (2 * 60, "2m ago"),
        (59 * 60, "59m ago"),
        (60 * 60, "1h ago"),  # 59m/60m boundary
        (3 * 3600, "3h ago"),
        (23 * 3600, "23h ago"),
        (24 * 3600, "1d ago"),  # 23h/24h boundary
        (2 * 86400, "2d ago"),
        (6 * 86400, "6d ago"),  # 6d/7d boundary (still relative)
    ],
)
def test_format_relative_age_relative_bands(delta_seconds: int, expected: str) -> None:
    epoch = _AGE_NOW_EPOCH - delta_seconds

    assert lp_render._format_relative_age(epoch, now=_age_now()) == expected


@pytest.mark.parametrize(
    "delta_seconds",
    [7 * 86400, 30 * 86400, 364 * 86400],  # 6d/7d and 364d/365d boundaries
)
def test_format_relative_age_recent_absolute_band(delta_seconds: int) -> None:
    epoch = _AGE_NOW_EPOCH - delta_seconds

    result = lp_render._format_relative_age(epoch, now=_age_now())

    assert result == lp_render.format_local(epoch, "%b %d")


def test_format_relative_age_old_absolute_band() -> None:
    epoch = _AGE_NOW_EPOCH - 365 * 86400

    result = lp_render._format_relative_age(epoch, now=_age_now())

    assert result == lp_render.format_local(epoch, "%b %Y")


def test_source_label_shape(log_dir: Path) -> None:
    epoch = _AGE_NOW_EPOCH
    _write_with_mtime(log_dir / "launch_failures.log", LAUNCH_LOG_BODY, epoch)
    source = next(s for s in log_sources() if s.id == "launch_failures")
    parsed = parse_local(epoch)
    assert parsed is not None
    now = to_local(parsed) + timedelta(minutes=2)

    label = lp_render.source_label(source, now=now)

    expected_size = lp_render.format_size_compact(len(LAUNCH_LOG_BODY.encode()))
    assert label.plain == f"● Launch & Fan-out Failures\n  {expected_size:<4} · 2m ago"
    assert label.no_wrap is True
    assert label.overflow == "ellipsis"


def test_source_label_empty_branch_shape(log_dir: Path) -> None:
    source = next(s for s in log_sources() if s.id == "launch_failures")

    label = lp_render.source_label(source)

    assert label.plain == "○ Launch & Fan-out Failures\n  empty"
    assert label.no_wrap is True
    assert label.overflow == "ellipsis"


def test_render_jsonl_source_is_pretty_not_raw(log_dir: Path) -> None:
    record = {"timestamp": "260617_143000", "event": "commit", "cl": "alpha"}
    write_log(log_dir / "events.jsonl", json.dumps(record) + "\n")
    source = next(s for s in log_sources() if s.id == "events")

    text = _render_log_detail(source).plain

    assert "commit" in text
    assert "cl=alpha" in text
    assert "{" not in text  # pretty-rendered, not raw JSON


def test_load_result_restores_log_source_by_id_after_reorder(
    log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = log_sources()
    assert len(sources) >= 3
    target = sources[2]
    reordered = [target, *sources[:2], *sources[3:]]
    monkeypatch.setattr(lp, "log_sources", lambda: reordered)

    result = lp._build_log_pane_load_result(2, selected_source_id=target.id)

    assert result.sources[result.selected_index].id == target.id


@pytest.mark.parametrize(
    "line, expected",
    [
        ("2026-06-17 10:00:00,123 ERROR sase.ace: boom", "red"),
        ("  error: RuntimeError: boom", "red"),
        ("RuntimeError: boom", "red"),
        ("Traceback (most recent call last):", "bold red"),
        ("2026-06-17 10:00:00,123 WARNING sase.ace: heads up", _GOLD),
        ('      File "x.py", line 1, in f', "dim"),
        ("=" * 72, "dim"),
    ],
)
def test_styled_log_line_severity(line: str, expected: str) -> None:
    assert str(_styled_log_line(line).style) == expected


def test_styled_log_line_colors_timestamp_prefix_cyan() -> None:
    line = "[2026-06-17 14:30:00 UTC] single launch failure: alpha"

    text = _styled_log_line(line)

    assert any(str(span.style) == _CYAN for span in text.spans)


def test_every_source_renders_without_error(log_dir: Path) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)
    write_log(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: x\n")
    write_log(log_dir / "runs.jsonl", json.dumps({"kind": "run"}) + "\n")
    write_log(log_dir / "events.jsonl", json.dumps({"event": "commit"}) + "\n")

    for source in log_sources():
        assert _render_log_detail(source).plain  # non-empty for each
