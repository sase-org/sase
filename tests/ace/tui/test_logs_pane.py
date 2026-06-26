"""Tests for the Admin Center Logs tab."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher, OptionList

from sase.logs import launch_log, run_log
from sase.ace.tui.logs import log_sources
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.logs_pane import (
    _CYAN,
    _GOLD,
    LogsPane,
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
    config_result = cp._LoadResult(view=None, error=None, token=("tok", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: config_result)
    plugins_result = pbp._PluginsLoadResult(catalog=None, error="stub", now=0.0)
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: plugins_result)
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: {},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [],
    )
    yield tmp_path


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


class _ModalTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def _wait_for_logs_loaded(pilot: object, pane: LogsPane) -> None:
    for _ in range(50):
        await pilot.pause(0.01)  # type: ignore[attr-defined]
        if not pane._loading:
            return
    raise AssertionError("Logs pane did not finish loading")


async def _open_logs_pane(pilot: object) -> tuple[ConfigCenterModal, LogsPane]:
    modal = ConfigCenterModal(initial_tab="logs")
    pilot.app.push_screen(modal)  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]
    pane = modal.query_one("#logs", LogsPane)
    await _wait_for_logs_loaded(pilot, pane)
    return modal, pane


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
# Pane pilot behavior
# --------------------------------------------------------------------------


async def test_logs_tab_opens_with_launch_failures_selected(log_dir: Path) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)

    async with _ModalTestApp().run_test() as pilot:
        modal, pane = await _open_logs_pane(pilot)

        assert isinstance(pilot.app.screen, ConfigCenterModal)
        assert modal._active_tab == "logs"
        option_list = pane.query_one("#log-source-list", OptionList)
        assert option_list.highlighted == 0  # launch_failures is the default

        assert "launch_failures.log" in pane._last_detail_text.plain


async def test_logs_tab_navigation_updates_detail(log_dir: Path) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)
    _write(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with _ModalTestApp().run_test() as pilot:
        _, pane = await _open_logs_pane(pilot)

        await pilot.press("j")
        await _wait_for_logs_loaded(pilot, pane)
        option_list = pane.query_one("#log-source-list", OptionList)
        assert option_list.highlighted == 1
        assert "tui.log" in pane._last_detail_text.plain

        # k navigates back up to launch failures.
        await pilot.press("k")
        await _wait_for_logs_loaded(pilot, pane)
        assert option_list.highlighted == 0


async def test_brackets_switch_admin_center_tabs_not_log_sources(
    log_dir: Path,
) -> None:
    async with _ModalTestApp().run_test() as pilot:
        modal, pane = await _open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)
        assert option_list.highlighted == 0

        await pilot.press("left_square_bracket")
        await pilot.pause()
        switcher = modal.query_one("#config-center-switcher", ContentSwitcher)
        assert modal._active_tab == "tasks"
        assert switcher.current == "tasks"
        assert option_list.highlighted == 0

        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert modal._active_tab == "logs"
        assert switcher.current == "logs"


async def test_logs_tab_refresh_and_scroll_and_dismiss(log_dir: Path) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)

    async with _ModalTestApp().run_test() as pilot:
        _, pane = await _open_logs_pane(pilot)

        # Log grows after the pane opened; r re-reads the tail.
        _write(
            log_dir / "launch_failures.log",
            _LAUNCH_LOG_BODY + "  error: SecondError: again\n",
        )
        await pilot.press("r")
        await _wait_for_logs_loaded(pilot, pane)
        assert "SecondError" in pane._last_detail_text.plain

        # Scrolling and dismissal don't error.
        await pilot.press("ctrl+d")
        await pilot.press("ctrl+u")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, ConfigCenterModal)


def _binding_action(key: str) -> str | None:
    """Action bound to *key* in ``LogsPane.BINDINGS`` (tuple or Binding)."""
    for binding in LogsPane.BINDINGS:
        if isinstance(binding, tuple):
            bind_key, action = binding[0], binding[1]
        else:
            bind_key, action = binding.key, binding.action
        if bind_key == key:
            return action
    return None


def test_logs_pane_binds_g_and_shift_g_to_scroll_extremes() -> None:
    assert _binding_action("g") == "scroll_to_top"
    assert _binding_action("G") == "scroll_to_bottom"


async def test_logs_tab_g_and_shift_g_scroll_detail_extremes(log_dir: Path) -> None:
    # Enough lines that the right detail pane is genuinely scrollable.
    _write(log_dir / "launch_failures.log", "".join(f"line {i}\n" for i in range(200)))

    async with _ModalTestApp().run_test() as pilot:
        _, pane = await _open_logs_pane(pilot)

        option_list = pane.query_one("#log-source-list", OptionList)
        highlighted_before = option_list.highlighted
        scroll = pane.query_one("#log-detail-scroll", VerticalScroll)

        # G jumps to the bottom of the detail pane.
        await pilot.press("G")
        await pilot.pause()
        assert scroll.max_scroll_y > 0  # pane really is scrollable
        assert scroll.scroll_y == scroll.max_scroll_y

        # g returns to the top.
        await pilot.press("g")
        await pilot.pause()
        assert scroll.scroll_y == 0

        # The highlighted log source is untouched by g / G.
        assert option_list.highlighted == highlighted_before
