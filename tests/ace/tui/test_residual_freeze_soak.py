"""Lowered-threshold integration soak for the residual ACE freeze fixes."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock

import pytest
from textual.widgets import Input

import sase.ace.tui.actions.agents._loading_disk as loading_disk
import sase.ace.tui.modals.prompt_history_modal as prompt_history_modal
from sase.ace.testing import AcePage
from sase.ace.tui.app import AceApp
from sase.ace.tui.modals.notification_modal_tags import NotificationTagTab
from sase.ace.tui.modals.prompt_history_modal import PromptHistoryModal
from sase.ace.tui.modals.revive_agent_modal import DismissedAgentSelectModal
from sase.history.prompt_catalog import PromptHistoryPage
from tests._agent_revive_helpers import make_agent
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT

_HITCH_THRESHOLD_SECONDS = 0.5
_BACKGROUND_HOLD_SECONDS = 0.65
_FREEZE_EVENTS = frozenset(
    {
        "tui_hitch",
        "tui_pump_hitch",
        "tui_stall",
        "tui_pump_stall",
    }
)


@dataclass(frozen=True)
class _WatchdogWindow:
    label: str
    started_ts: float
    ended_ts: float
    stack_markers: tuple[str, ...] = ()


class _WatchdogWindows:
    """Record exact wall-clock windows for deliberately blocked worker bodies."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._windows: list[_WatchdogWindow] = []

    @contextmanager
    def record(
        self,
        label: str,
        *,
        stack_markers: tuple[str, ...],
    ) -> Iterator[None]:
        started_ts = time.time()
        try:
            yield
        finally:
            window = _WatchdogWindow(
                label=label,
                started_ts=started_ts,
                ended_ts=time.time(),
                stack_markers=stack_markers,
            )
            with self._lock:
                self._windows.append(window)

    def snapshot(self) -> tuple[_WatchdogWindow, ...]:
        with self._lock:
            return tuple(self._windows)


def _configure_lowered_watchdog(
    monkeypatch: pytest.MonkeyPatch,
    log_path: Path,
) -> None:
    monkeypatch.setenv("SASE_TUI_STALL_PATH", str(log_path))
    monkeypatch.setenv(
        "SASE_TUI_HITCH_THRESHOLD_SECONDS", str(_HITCH_THRESHOLD_SECONDS)
    )
    monkeypatch.setenv(
        "SASE_TUI_PUMP_HITCH_THRESHOLD_SECONDS", str(_HITCH_THRESHOLD_SECONDS)
    )
    monkeypatch.setenv("SASE_TUI_STALL_THRESHOLD_SECONDS", "1.0")
    monkeypatch.setenv("SASE_TUI_PUMP_STALL_THRESHOLD_SECONDS", "1.0")
    monkeypatch.setenv("SASE_TUI_STALL_POLL_INTERVAL", "0.02")
    monkeypatch.setenv("SASE_TUI_PUMP_STALL_POLL_INTERVAL", "0.02")


async def _wait_for_thread_event(
    event: Event,
    *,
    timeout: float = LOAD_TOLERANT_TIMEOUT,
) -> None:
    observed = await asyncio.wait_for(
        asyncio.to_thread(event.wait, timeout),
        timeout=timeout + 1.0,
    )
    assert observed


async def _hold_past_hitch_threshold() -> None:
    assert _BACKGROUND_HOLD_SECONDS > _HITCH_THRESHOLD_SECONDS
    await asyncio.sleep(_BACKGROUND_HOLD_SECONDS)


async def _press_within_deadline(page: AcePage, key: str) -> None:
    await asyncio.wait_for(
        page.press(key),
        timeout=LOAD_TOLERANT_TIMEOUT,
    )


def _read_events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _iter_stack_lines(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_stack_lines(item)
        return
    if not isinstance(value, dict):
        return
    for key in ("stack", "await_chain"):
        yield from _iter_stack_lines(value.get(key))


def _record_causal_stack_text(record: dict[str, object]) -> str:
    # Pump-stall task/worker stacks include broad diagnostic context. Attribute
    # fixed-path failures only to the UI-thread stack that the watchdog sampled.
    lines: list[str] = []
    lines.extend(_iter_stack_lines(record.get("main_thread_stack")))
    return "\n".join(lines)


def _record_implicates_window(
    record: dict[str, object],
    window: _WatchdogWindow,
) -> bool:
    if not window.stack_markers:
        return True
    stack_text = _record_causal_stack_text(record)
    return any(marker in stack_text for marker in window.stack_markers)


def _assert_no_fixed_path_freezes(
    records: list[dict[str, object]],
    windows: tuple[_WatchdogWindow, ...],
) -> None:
    observed: list[tuple[str, dict[str, object]]] = []
    for record in records:
        if record.get("event") not in _FREEZE_EVENTS:
            continue
        event_ts = record.get("ts")
        if not isinstance(event_ts, (int, float)):
            continue
        for window in windows:
            if (
                window.started_ts <= event_ts <= window.ended_ts
                and _record_implicates_window(record, window)
            ):
                observed.append((window.label, record))
                break
    assert observed == [], (
        f"watchdog events during controlled slow-work windows: {observed!r}"
    )


def test_real_app_watchdog_context_includes_last_action() -> None:
    app = AceApp(auto_start_axe=False)
    app._last_input_action = "next_tab"

    context = app._tui_stall_context()

    assert context["last_action"] == "next_tab"


def test_watchdog_windows_ignore_unrelated_session_hitches() -> None:
    windows = (
        _WatchdogWindow(
            "startup",
            10.0,
            11.0,
            stack_markers=("slow_startup_read",),
        ),
    )
    records = [
        {
            "event": "tui_hitch",
            "ts": 9.9,
            "main_thread_stack": ["slow_startup_read"],
        },
        {
            "event": "tui_pump_hitch",
            "ts": 11.1,
            "main_thread_stack": ["slow_startup_read"],
        },
        {
            "event": "tui_stall",
            "ts": 10.5,
            "main_thread_stack": ["commits_rendering.build_commit_detail"],
        },
    ]

    _assert_no_fixed_path_freezes(records, windows)


def test_watchdog_windows_reject_fixed_path_hitches() -> None:
    windows = (
        _WatchdogWindow(
            "prompt_history",
            10.0,
            11.0,
            stack_markers=("load_prompt_record_page",),
        ),
    )
    records = [
        {
            "event": "tui_pump_hitch",
            "ts": 10.5,
            "main_thread_stack": ["load_prompt_record_page"],
        },
    ]

    with pytest.raises(AssertionError, match="prompt_history"):
        _assert_no_fixed_path_freezes(records, windows)


def test_watchdog_windows_ignore_worker_only_fixed_path_stacks() -> None:
    windows = (
        _WatchdogWindow(
            "loader_cleanup",
            10.0,
            11.0,
            stack_markers=("compute_loader_cleanup",),
        ),
    )
    records = [
        {
            "event": "tui_pump_stall",
            "ts": 10.5,
            "main_thread_stack": ["commits_rendering.build_commit_detail"],
            "asyncio_task_stacks": [{"name": "pump-handler", "stack": ["unrelated"]}],
            "worker_thread_stacks": [
                {"name": "worker", "stack": ["compute_loader_cleanup"]}
            ],
        },
    ]

    _assert_no_fixed_path_freezes(records, windows)


@pytest.mark.asyncio
async def test_lowered_threshold_soak_keeps_fixed_paths_responsive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slow workers may cross the hitch threshold without stalling either pump."""
    stall_log = tmp_path / "tui_stalls.jsonl"
    _configure_lowered_watchdog(monkeypatch, stall_log)
    watchdog_windows = _WatchdogWindows()

    startup_started = Event()
    startup_release = Event()

    def slow_startup_read(
        _self: AceApp,
    ) -> tuple[set[str], set[tuple[str, str]], list[NotificationTagTab]]:
        with watchdog_windows.record(
            "startup",
            stack_markers=("_read_notifications_for_startup", "slow_startup_read"),
        ):
            startup_started.set()
            startup_release.wait(timeout=LOAD_TOLERANT_TIMEOUT)
        return set(), set(), []

    monkeypatch.setattr(
        AceApp,
        "_read_notifications_for_startup",
        slow_startup_read,
    )

    async with AcePage(
        wait_for_startup_state=False,
        startup_policy="real",
    ) as page:
        try:
            await _wait_for_thread_event(startup_started)
            await _press_within_deadline(page, "tab")
            await page.expect_state("tab", "axe", timeout=LOAD_TOLERANT_TIMEOUT)
            await _hold_past_hitch_threshold()
        finally:
            startup_release.set()
        await page.wait_for(
            lambda _state: page.app._mount_state_loads_done,
            timeout=5.0,
        )

        history_started = Event()
        history_release = Event()

        def slow_history_page(**_kwargs: object) -> PromptHistoryPage:
            with watchdog_windows.record(
                "prompt_history",
                stack_markers=("load_prompt_record_page", "slow_history_page"),
            ):
                history_started.set()
                history_release.wait(timeout=LOAD_TOLERANT_TIMEOUT)
            return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

        monkeypatch.setattr(
            prompt_history_modal,
            "load_prompt_record_page",
            slow_history_page,
        )
        history_modal = PromptHistoryModal()
        page.app.push_screen(history_modal)
        try:
            await _wait_for_thread_event(history_started)
            history_filter = history_modal.query_one(
                "#prompt-history-filter-input", Input
            )
            await _press_within_deadline(page, "h")
            assert history_filter.value == "h"
            await _hold_past_hitch_threshold()
        finally:
            history_release.set()
        await page.wait_for(
            lambda _state: history_modal._history_loaded_once,
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        history_modal.dismiss(None)
        await page.expect_no_modal(timeout=LOAD_TOLERANT_TIMEOUT)

        archive_started = Event()
        archive_release = Event()
        dismissed_agent = make_agent(
            cl_name="verification",
            raw_suffix="20260717090000",
        )

        def slow_archive_page() -> tuple[list[object], list[object], bool]:
            with watchdog_windows.record(
                "revive_archive",
                stack_markers=("_page_loader", "slow_archive_page"),
            ):
                archive_started.set()
                archive_release.wait(timeout=LOAD_TOLERANT_TIMEOUT)
            return [dismissed_agent], [dismissed_agent], True

        archive_modal = DismissedAgentSelectModal(
            [],
            loading_archive=True,
            page_loader=slow_archive_page,  # type: ignore[arg-type]
        )
        page.app.push_screen(archive_modal)
        try:
            await _wait_for_thread_event(archive_started)
            archive_filter = archive_modal.query_one("#dismissed-filter", Input)
            await _press_within_deadline(page, "v")
            assert archive_filter.value == "v"
            await _hold_past_hitch_threshold()
        finally:
            archive_release.set()
        await page.wait_for(
            lambda _state: not archive_modal._initial_loading,
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        archive_modal.dismiss(None)
        await page.expect_no_modal(timeout=LOAD_TOLERANT_TIMEOUT)

        cleanup_started = Event()
        cleanup_release = Event()

        def slow_loader_cleanup(
            *_args: object,
        ) -> tuple[set[object], set[str]]:
            with watchdog_windows.record(
                "loader_cleanup",
                stack_markers=("compute_loader_cleanup", "slow_loader_cleanup"),
            ):
                cleanup_started.set()
                cleanup_release.wait(timeout=LOAD_TOLERANT_TIMEOUT)
            return set(), set()

        monkeypatch.setattr(
            loading_disk,
            "compute_loader_cleanup",
            slow_loader_cleanup,
        )
        page.app._schedule_loader_cleanup(
            {dismissed_agent.identity},
            [],
            source="freeze_verification",
            load_kind="full",
        )
        try:
            await _wait_for_thread_event(cleanup_started)
            previous_tab = page.app.current_tab
            await _press_within_deadline(page, "tab")
            assert page.app.current_tab != previous_tab
            await _hold_past_hitch_threshold()
        finally:
            cleanup_release.set()
        await page.wait_for(
            lambda _state: (
                not page.app._loader_cleanup_running
                and not page.app._loader_cleanup_async_tasks
            ),
            timeout=LOAD_TOLERANT_TIMEOUT,
        )

    records = _read_events(stall_log)
    _assert_no_fixed_path_freezes(records, watchdog_windows.snapshot())
