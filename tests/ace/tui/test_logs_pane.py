"""Tests for the Admin Center Logs tab."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher, OptionList

from sase.ace.testing import AcePage
from sase.logs import launch_log, run_log, toast_log
from sase.ace.tui.logs import log_sources
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import logs_pane as lp
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
    monkeypatch.setattr(
        toast_log,
        "TUI_TOASTS_JSONL",
        str(tmp_path / "tui_toasts.jsonl"),
    )
    toast_log._reset_current_toast_session(
        session_started_at=datetime(2026, 7, 7, 9, 12, tzinfo=UTC),
        pid=1234,
    )
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
    toast_log.flush_toasts(timeout=1.0)
    toast_log._reset_current_toast_session()


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _toast_json(
    *,
    timestamp: str,
    session_id: str,
    session_started_at: str,
    pid: int,
    message: str,
    severity: str = "information",
    title: str = "",
) -> str:
    return json.dumps(
        {
            "timestamp": timestamp,
            "session_id": session_id,
            "session_started_at": session_started_at,
            "pid": pid,
            "severity": severity,
            "title": title,
            "message": message,
        }
    )


def _write_toast_records(records: list[str]) -> None:
    path = toast_log.tui_toasts_jsonl_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(records) + "\n", encoding="utf-8")


def _style_at(text: Text, needle: str) -> set[str]:
    pos = text.plain.index(needle)
    return {
        str(span.style)
        for span in text.spans
        if span.start <= pos < span.end and span.style is not None
    }


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


def _option_plain(option_list: OptionList, index: int) -> str:
    option = option_list.get_option_at_index(index)
    assert isinstance(option.prompt, Text)
    return option.prompt.plain


def _logs_hint_text(pane: LogsPane) -> str:
    return pane._hints()


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


def test_render_toasts_groups_sessions_newest_first(log_dir: Path) -> None:
    current_session = toast_log.current_toast_session()
    _write_toast_records(
        [
            _toast_json(
                timestamp="2026-07-06T22:03:12Z",
                session_id="20260706T220100Z-98111",
                session_started_at="2026-07-06T22:01:00Z",
                pid=98111,
                message="ChangeSpec must be Ready to mail",
                severity="warning",
            ),
            _toast_json(
                timestamp="2026-07-06T22:15:33Z",
                session_id="20260706T220100Z-98111",
                session_started_at="2026-07-06T22:01:00Z",
                pid=98111,
                message="Saved query to slot 2",
            ),
            _toast_json(
                timestamp="2026-07-07T00:01:00Z",
                session_id="20260706T235500Z-900",
                session_started_at="2026-07-06T23:55:00Z",
                pid=900,
                message="First toast after midnight",
                severity="warning",
            ),
            _toast_json(
                timestamp="2026-07-07T09:12:10Z",
                session_id=current_session.session_id,
                session_started_at=current_session.session_started_at,
                pid=current_session.pid,
                message="Mailing my-change...",
            ),
            _toast_json(
                timestamp="2026-07-07T09:12:41Z",
                session_id=current_session.session_id,
                session_started_at=current_session.session_started_at,
                pid=current_session.pid,
                message="Refreshed",
            ),
            _toast_json(
                timestamp="2026-07-07T09:12:42Z",
                session_id=current_session.session_id,
                session_started_at=current_session.session_started_at,
                pid=current_session.pid,
                message="Refreshed",
            ),
            _toast_json(
                timestamp="2026-07-07T09:13:47Z",
                session_id=current_session.session_id,
                session_started_at=current_session.session_started_at,
                pid=current_session.pid,
                message="PR is not set",
                severity="warning",
            ),
            _toast_json(
                timestamp="2026-07-07T09:14:03Z",
                session_id=current_session.session_id,
                session_started_at=current_session.session_started_at,
                pid=current_session.pid,
                message="boom\ntrace line",
                severity="error",
                title="Workflow error",
            ),
        ]
    )
    source = next(s for s in log_sources() if s.id == "tui_toasts")

    text = _render_log_detail(source)
    plain = text.plain

    assert "TUI Toasts" in plain
    assert "8 toasts" in plain
    assert plain.index("This session") < plain.index("pid 900")
    assert plain.index("pid 900") < plain.index("pid 98111")
    assert plain.index("Workflow error") < plain.index("PR is not set")
    assert plain.index("PR is not set") < plain.index("Refreshed")
    assert "Refreshed  ×2" in plain
    assert plain.count("Refreshed") == 1
    assert "20:01:00" in plain
    assert "boom\n            trace line" in plain
    assert "✖" in plain
    assert "⚠" in plain
    assert "·" in plain
    assert f"pid {current_session.pid}" in plain

    assert f"bold {_GOLD}" in _style_at(text, "This session")
    assert "red" in _style_at(text, "boom")
    assert _GOLD in _style_at(text, "PR is not set")
    assert _CYAN in _style_at(text, "05:14:03")


def test_render_empty_toasts_source_shows_notification_history_copy(
    log_dir: Path,
) -> None:
    source = next(s for s in log_sources() if s.id == "tui_toasts")

    text = _render_log_detail(source).plain

    assert "No toasts yet" in text
    assert "notifications shown in the TUI will appear here" in text


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


async def test_ace_app_notify_records_toast_history(log_dir: Path) -> None:
    async with AcePage(query='"toast"') as page:
        session = toast_log.current_toast_session()

        page.app.notify("Info toast")
        page.app.notify("Warn toast", severity="warning")
        page.app.notify("Error toast", title="Failure", severity="error")

        assert toast_log.flush_toasts(timeout=2.0)

    records = [
        record
        for record in toast_log.read_recent_toasts()
        if record.message in {"Info toast", "Warn toast", "Error toast"}
    ]
    assert [record.message for record in records] == [
        "Info toast",
        "Warn toast",
        "Error toast",
    ]
    assert {record.session_id for record in records} == {session.session_id}
    assert records[0].severity == "information"
    assert records[1].severity == "warning"
    assert records[2].severity == "error"
    assert records[2].title == "Failure"


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


async def test_logs_tab_apostrophe_enters_jump_mode_with_hints(
    log_dir: Path,
) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)
    _write(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with _ModalTestApp().run_test() as pilot:
        _, pane = await _open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.pause()

        assert pane._log_jump_mode_active is True
        assert _option_plain(option_list, 0).startswith("[0] ● Launch")
        assert _option_plain(option_list, 1).startswith("[1] ● TUI Diagnostics")
        assert "JUMP ' first" in _logs_hint_text(pane)


async def test_logs_tab_jump_hint_selects_source_and_loads_detail(
    log_dir: Path,
) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)
    _write(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with _ModalTestApp().run_test() as pilot:
        _, pane = await _open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.press("1")
        await _wait_for_logs_loaded(pilot, pane)

        assert pane._log_jump_mode_active is False
        assert pane._log_jump_back_stack == [0]
        assert option_list.highlighted == 1
        assert "tui.log" in pane._last_detail_text.plain
        assert not _option_plain(option_list, 1).startswith("[1]")


async def test_logs_tab_digit_hint_does_not_switch_admin_center_tabs(
    log_dir: Path,
) -> None:
    async with _ModalTestApp().run_test() as pilot:
        modal, pane = await _open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)
        switcher = modal.query_one("#config-center-switcher", ContentSwitcher)
        assert len(pane._source_options) >= 3

        await pilot.press("apostrophe")
        await pilot.press("2")
        await _wait_for_logs_loaded(pilot, pane)

        assert pane._log_jump_mode_active is False
        assert modal._active_tab == "logs"
        assert switcher.current == "logs"
        assert option_list.highlighted == 2


async def test_logs_tab_apostrophe_in_jump_mode_returns_to_previous_source(
    log_dir: Path,
) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)
    _write(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with _ModalTestApp().run_test() as pilot:
        _, pane = await _open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.press("1")
        await _wait_for_logs_loaded(pilot, pane)
        assert option_list.highlighted == 1

        await pilot.press("apostrophe")
        await pilot.pause()
        assert "JUMP ' back" in _logs_hint_text(pane)

        await pilot.press("apostrophe")
        await _wait_for_logs_loaded(pilot, pane)

        assert option_list.highlighted == 0
        assert pane._log_jump_back_stack == []
        assert "launch_failures.log" in pane._last_detail_text.plain


async def test_logs_tab_apostrophe_without_history_jumps_to_first_source(
    log_dir: Path,
) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)
    _write(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with _ModalTestApp().run_test() as pilot:
        _, pane = await _open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)

        await pilot.press("j")
        await _wait_for_logs_loaded(pilot, pane)
        assert option_list.highlighted == 1
        assert pane._log_jump_back_stack == []

        await pilot.press("apostrophe")
        await pilot.press("apostrophe")
        await _wait_for_logs_loaded(pilot, pane)

        assert option_list.highlighted == 0
        assert pane._log_jump_back_stack == [1]
        assert "launch_failures.log" in pane._last_detail_text.plain


async def test_logs_tab_escape_cancels_jump_mode_without_closing_modal(
    log_dir: Path,
) -> None:
    async with _ModalTestApp().run_test() as pilot:
        _, pane = await _open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.pause()
        assert pane._log_jump_mode_active is True

        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ConfigCenterModal)
        assert pane._log_jump_mode_active is False
        assert option_list.highlighted == 0
        assert not _option_plain(option_list, 0).startswith("[0]")
        assert "': jump" in _logs_hint_text(pane)


async def test_logs_tab_jump_mode_reuses_cached_source_labels(
    log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(log_dir / "launch_failures.log", _LAUNCH_LOG_BODY)

    async with _ModalTestApp().run_test() as pilot:
        _, pane = await _open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)
        cached_plain = _option_plain(option_list, 0)

        def fail_source_label(_source: object) -> Text:
            raise AssertionError("_source_label should not run during jump rendering")

        monkeypatch.setattr(lp, "_source_label", fail_source_label)

        await pilot.press("apostrophe")
        await pilot.pause()

        assert _option_plain(option_list, 0) == f"[0] {cached_plain}"


async def test_tab_switches_admin_center_tabs_and_brackets_do_not(
    log_dir: Path,
) -> None:
    async with _ModalTestApp().run_test() as pilot:
        modal, pane = await _open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)
        assert option_list.highlighted == 0

        await pilot.press("left_square_bracket")
        await pilot.pause()
        switcher = modal.query_one("#config-center-switcher", ContentSwitcher)
        assert modal._active_tab == "logs"
        assert switcher.current == "logs"
        assert option_list.highlighted == 0

        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert modal._active_tab == "logs"
        assert switcher.current == "logs"
        assert option_list.highlighted == 0

        await pilot.press("tab")
        await pilot.pause()
        assert modal._active_tab == "projects"
        assert switcher.current == "projects"

        await pilot.press("shift+tab")
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
