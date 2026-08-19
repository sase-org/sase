"""Shared fixtures and helpers for the Admin Center Logs tab tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from sase.ace.testing import wait_for
from sase.logs import launch_log, run_log, toast_log
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.logs_pane import LogsPane
from sase.logs import RegisteredError

LAUNCH_LOG_BODY = (
    "=" * 72 + "\n"
    "[2026-06-17 14:30:00 UTC] single launch failure: alpha  "
    "[err_260617_143000_7f3a9c]\n"
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


def write_log(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


class ModalTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def wait_for_logs_loaded(pilot: object, pane: LogsPane) -> None:
    await wait_for(pilot, lambda: not pane._loading)


async def open_logs_pane(
    pilot: object,
    *,
    error_target: RegisteredError | None = None,
) -> tuple[ConfigCenterModal, LogsPane]:
    modal = ConfigCenterModal(initial_tab="logs", log_error_target=error_target)
    pilot.app.push_screen(modal)  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]
    pane = modal.query_one("#logs", LogsPane)
    await wait_for_logs_loaded(pilot, pane)
    return modal, pane
