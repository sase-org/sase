"""Tests for the Refresh panel single-key chooser."""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.actions.event_refresh._freshness import freshness_label
from sase.ace.tui.modals.refresh_panel_modal import (
    RefreshChoice,
    RefreshPanelModal,
    RefreshRow,
    UsageRowStatus,
    _load_refresh_usage_status,
)
from sase.llm_provider.usage.config import UsageMetricsSettings
from sase.llm_provider.usage.presentation import age_label
from tests._usage_view_helpers import (
    usage_provider,
    usage_view_snapshot,
    usage_window,
)


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


THIS_TAB_CHIP = freshness_label(12.0)
FULL_HISTORY_CHIP = freshness_label(7200.0)
EVERYTHING_CHIP = freshness_label(None)


def _rows(
    *,
    usage_unavailable: str | None = None,
    usage_chip: str = "checking…",
) -> tuple[RefreshRow, ...]:
    return (
        RefreshRow(
            choice="this_tab",
            key="r",
            aliases=("R", "enter", "1"),
            title="This tab",
            target="Agents",
            subtitle="Reload the visible inbox from the index.",
            chip=THIS_TAB_CHIP,
            tone="primary",
        ),
        RefreshRow(
            choice="full_history",
            key="f",
            aliases=("2",),
            title="Full history",
            target="Agents",
            subtitle="Rescan every source artifact. Slower.",
            chip=FULL_HISTORY_CHIP,
        ),
        RefreshRow(
            choice="usage",
            key="u",
            aliases=("3",),
            title="Usage windows",
            target="providers",
            subtitle="Re-probe provider subscription limits.",
            chip=usage_chip,
            unavailable_reason=usage_unavailable,
        ),
        RefreshRow(
            choice="everything",
            key="a",
            aliases=("4",),
            title="Everything",
            target="",
            subtitle="Every surface, full history, and usage.",
            chip=EVERYTHING_CHIP,
            tone="accent",
        ),
    )


def _ready_usage(
    *,
    chip: str = "6m",
    unavailable_reason: str | None = None,
    provider_count: int = 3,
) -> UsageRowStatus:
    return UsageRowStatus(
        provider_count=provider_count,
        chip=chip,
        unavailable_reason=unavailable_reason,
    )


def _modal(
    *,
    initial_choice: RefreshChoice = "this_tab",
    banner: str | None = None,
    auto_refresh_label: str | None = "auto-refresh every 10s · next in 4s",
    load_usage_status: Any | None = None,
    usage_unavailable: str | None = None,
) -> RefreshPanelModal:
    loader = load_usage_status or (
        lambda: _ready_usage(unavailable_reason=usage_unavailable)
    )
    return RefreshPanelModal(
        tab_label="Agents",
        rows=_rows(usage_unavailable=usage_unavailable),
        auto_refresh_label=auto_refresh_label,
        initial_choice=initial_choice,
        banner=banner,
        load_usage_status=loader,
    )


def _row_plain(modal: RefreshPanelModal, choice: RefreshChoice) -> str:
    return modal.query_one(f"#refresh-panel-row-{choice}", Static).render().plain


def _selected_choice(modal: RefreshPanelModal) -> RefreshChoice:
    for row in modal._rows:
        widget = modal.query_one(f"#refresh-panel-row-{row.choice}", Static)
        if widget.has_class("refresh-panel-row-selected"):
            return row.choice
    raise AssertionError("no selected refresh row")


@pytest.mark.parametrize(
    ("key", "choice"),
    [
        ("r", "this_tab"),
        ("R", "this_tab"),
        ("1", "this_tab"),
        ("f", "full_history"),
        ("2", "full_history"),
        ("u", "usage"),
        ("3", "usage"),
        ("a", "everything"),
        ("4", "everything"),
    ],
)
async def test_letter_and_numeric_aliases_return_choice(
    key: str, choice: RefreshChoice
) -> None:
    result: object = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(_modal(), on_dismiss)
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()

    assert result == choice


async def test_enter_follows_the_cursor() -> None:
    result: object = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        modal = _modal()
        pilot.app.push_screen(modal, on_dismiss)
        await pilot.pause()
        assert _selected_choice(modal) == "this_tab"

        await pilot.press("j")
        await pilot.pause()
        assert _selected_choice(modal) == "full_history"

        await pilot.press("enter")
        await pilot.pause()

    assert result == "full_history"


async def test_jk_move_and_wrap() -> None:
    async with _TestApp().run_test() as pilot:
        modal = _modal()
        dismissed: list[object] = []
        modal.dismiss = dismissed.append  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("k")
        await pilot.pause()
        assert _selected_choice(modal) == "everything"

        await pilot.press("j")
        await pilot.pause()
        assert _selected_choice(modal) == "this_tab"

        await pilot.press("down")
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert _selected_choice(modal) == "usage"

        await pilot.press("up")
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert _selected_choice(modal) == "this_tab"

    assert dismissed == []


@pytest.mark.parametrize("key", ["escape", "q"])
async def test_cancel_returns_none(key: str) -> None:
    result: object = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(_modal(), on_dismiss)
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()

    assert result is None


async def test_unavailable_usage_row_notifies_and_does_not_dismiss() -> None:
    reason = "subscription usage collection is disabled"

    async with _TestApp().run_test() as pilot:
        modal = _modal(usage_unavailable=reason)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        dismissed: list[object] = []
        modal.dismiss = dismissed.append  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await wait_for(
            pilot,
            lambda: modal._usage_loaded,
        )

        await pilot.press("u")
        await pilot.pause()

        modal.notify.assert_called_once_with(reason, severity="warning")
        assert dismissed == []
        assert len(pilot.app.screen_stack) == 2

        await pilot.press("j")
        await pilot.press("j")
        await pilot.pause()
        assert _selected_choice(modal) == "usage"
        modal.notify.reset_mock()
        await pilot.press("enter")
        await pilot.pause()

        modal.notify.assert_called_once_with(reason, severity="warning")
        assert dismissed == []


async def test_initial_choice_positions_the_cursor() -> None:
    result: object = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        modal = _modal(initial_choice="full_history")
        pilot.app.push_screen(modal, on_dismiss)
        await pilot.pause()
        assert _selected_choice(modal) == "full_history"

        await pilot.press("enter")
        await pilot.pause()

    assert result == "full_history"


async def test_banner_renders_only_when_supplied() -> None:
    async with _TestApp().run_test() as pilot:
        modal = _modal(banner=",y lives here now — press f")
        pilot.app.push_screen(modal)
        await pilot.pause()
        banner = modal.query_one("#refresh-panel-banner", Static)
        assert ",y lives here now" in banner.render().plain

    async with _TestApp().run_test() as pilot:
        modal = _modal(banner=None)
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert len(modal.query("#refresh-panel-banner")) == 0


async def test_stubbed_usage_status_patches_usage_row_after_worker() -> None:
    released = threading.Event()

    def load_usage_status() -> UsageRowStatus:
        released.wait(timeout=5)
        return UsageRowStatus(
            provider_count=3,
            chip="6m",
            unavailable_reason=None,
        )

    async with _TestApp().run_test() as pilot:
        modal = _modal(load_usage_status=load_usage_status)
        try:
            pilot.app.push_screen(modal)
            await pilot.pause()
            assert "checking…" in _row_plain(modal, "usage")
            released.set()
            await wait_for(
                pilot,
                lambda: "6m" in _row_plain(modal, "usage"),
            )
            plain = _row_plain(modal, "usage")
            assert "3 providers" in plain
            assert "checking…" not in plain
        finally:
            released.set()


async def test_row_chips_use_freshness_label_output() -> None:
    async with _TestApp().run_test() as pilot:
        modal = _modal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert THIS_TAB_CHIP in _row_plain(modal, "this_tab")
        assert FULL_HISTORY_CHIP in _row_plain(modal, "full_history")
        assert EVERYTHING_CHIP in _row_plain(modal, "everything")
        assert modal.tab_label == "Agents"
        header = modal.query_one("#refresh-panel-header", Static)
        assert "auto-refresh every 10s" in header.render().plain


async def test_header_absent_when_auto_refresh_label_omitted() -> None:
    async with _TestApp().run_test() as pilot:
        modal = _modal(auto_refresh_label=None)
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert len(modal.query("#refresh-panel-header")) == 0


def test_load_refresh_usage_status_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.ace.tui.modals.refresh_panel_modal as module

    monkeypatch.setattr(
        module,
        "get_usage_metrics_settings",
        lambda: UsageMetricsSettings(enabled=False),
    )

    status = _load_refresh_usage_status()

    assert status.provider_count == 0
    assert status.unavailable_reason == "subscription usage collection is disabled"


def test_load_refresh_usage_status_without_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.modals.refresh_panel_modal as module

    monkeypatch.setattr(
        module,
        "get_usage_metrics_settings",
        lambda: UsageMetricsSettings(enabled=True),
    )
    monkeypatch.setattr(module, "eligible_usage_providers", lambda: ())

    status = _load_refresh_usage_status()

    assert status.provider_count == 0
    assert status.unavailable_reason == "No eligible providers."


def test_load_refresh_usage_status_uses_newest_window_age_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.modals.refresh_panel_modal as module

    monkeypatch.setattr(
        module,
        "get_usage_metrics_settings",
        lambda: UsageMetricsSettings(enabled=True),
    )
    monkeypatch.setattr(
        module,
        "eligible_usage_providers",
        lambda: ("codex", "grok", "claude"),
    )
    snapshot = usage_view_snapshot(
        usage_provider("codex", windows=[usage_window(age_seconds=3600)]),
        usage_provider("grok", windows=[usage_window(age_seconds=30)]),
    )
    monkeypatch.setattr(module, "load_usage_view_snapshot", lambda: snapshot)

    status = _load_refresh_usage_status()

    assert status.provider_count == 3
    assert status.unavailable_reason is None
    assert status.chip == age_label({"age_seconds": 30})


def test_unmount_cancels_active_usage_worker() -> None:
    modal = _modal()
    worker = MagicMock()
    worker.is_finished = False
    modal._usage_worker = worker

    modal.on_unmount()

    worker.cancel.assert_called_once_with()
