"""Tests for the ``,L`` Log panel modal (Phase 2)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.logs import launch_log, run_log
from sase.ace.tui.logs import log_sources
from sase.ace.tui.modals.log_modal import (
    _CYAN,
    _GOLD,
    LogModal,
    _styled_log_line,
    _render_log_detail,
)

_LAUNCH_LOG_BODY = (
    "=" * 72 + "\n"
    "[2026-06-17 14:30:00 UTC] single launch failure: alpha\n"
    "  error: RuntimeError: boom\n"
    "  project: demo\n"
    "\n"
    "  traceback:\n"
    '    File "x.py", line 1, in f\n'
    "    RuntimeError: boom\n"
)


@pytest.fixture
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect every canonical log path under ``tmp_path``."""
    monkeypatch.setattr(launch_log, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(run_log, "LOGS_DIR", str(tmp_path))
    yield tmp_path


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


class _ModalTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


# --------------------------------------------------------------------------
# _render_log_detail / colorization (pure, no app)
# --------------------------------------------------------------------------


def test_render_text_source_includes_header_and_body(log_dir: Path) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)
    source = next(s for s in log_sources() if s.id == "launch_failures")

    text = _render_log_detail(source).plain

    assert str(source.path) in text  # header path
    assert "single launch failure: alpha" in text
    assert "RuntimeError: boom" in text


def test_render_empty_source_shows_friendly_empty_state(log_dir: Path) -> None:
    source = next(s for s in log_sources() if s.id == "launch_failures")

    text = _render_log_detail(source).plain

    assert "No launch failures logged" in text


def test_render_jsonl_source_is_pretty_not_raw(log_dir: Path) -> None:
    record = {"timestamp": "260617_143000", "event": "commit", "cl": "alpha"}
    _write(log_dir / "events.jsonl", json.dumps(record) + "\n")
    source = next(s for s in log_sources() if s.id == "events")

    text = _render_log_detail(source).plain

    assert "commit" in text
    assert "cl=alpha" in text
    assert "{" not in text  # pretty-rendered, not raw JSON


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
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)
    _write(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: x\n")
    _write(log_dir / "runs.jsonl", json.dumps({"kind": "run"}) + "\n")
    _write(log_dir / "events.jsonl", json.dumps({"event": "commit"}) + "\n")

    for source in log_sources():
        assert _render_log_detail(source).plain  # non-empty for each


# --------------------------------------------------------------------------
# Modal pilot behavior
# --------------------------------------------------------------------------


async def test_modal_opens_with_launch_failures_selected(log_dir: Path) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)

    async with _ModalTestApp().run_test() as pilot:
        modal = LogModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert isinstance(pilot.app.screen, LogModal)
        option_list = modal.query_one("#log-source-list", OptionList)
        assert option_list.highlighted == 0  # launch_failures is the default

        assert "launch_failures.log" in modal._last_detail_text.plain


async def test_modal_cycle_and_navigate_update_detail(log_dir: Path) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)
    _write(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with _ModalTestApp().run_test() as pilot:
        modal = LogModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        # ] cycles to the next source (tui diagnostics) and repaints detail.
        await pilot.press("right_square_bracket")
        await pilot.pause()
        option_list = modal.query_one("#log-source-list", OptionList)
        assert option_list.highlighted == 1
        assert "tui.log" in modal._last_detail_text.plain

        # k navigates back up to launch failures.
        await pilot.press("k")
        await pilot.pause()
        assert option_list.highlighted == 0


async def test_modal_cycle_prev_wraps_to_last(log_dir: Path) -> None:
    async with _ModalTestApp().run_test() as pilot:
        modal = LogModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("left_square_bracket")
        await pilot.pause()

        option_list = modal.query_one("#log-source-list", OptionList)
        assert option_list.highlighted == len(modal._sources) - 1


async def test_modal_refresh_and_scroll_and_dismiss(log_dir: Path) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)

    async with _ModalTestApp().run_test() as pilot:
        modal = LogModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        # Log grows after the modal opened; r re-reads the tail.
        _write(
            log_dir / "launch_failures.log",
            _LAUNCH_LOG_BODY + "  error: SecondError: again\n",
        )
        await pilot.press("r")
        await pilot.pause()
        assert "SecondError" in modal._last_detail_text.plain

        # Scrolling and dismissal don't error.
        await pilot.press("ctrl+d")
        await pilot.press("ctrl+u")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, LogModal)
