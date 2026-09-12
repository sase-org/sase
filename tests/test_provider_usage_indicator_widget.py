"""ProviderUsageIndicator widget lifecycle tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rich.text import Text
from textual.worker import WorkerState

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import provider_usage_indicator as indicator_module
from sase.ace.tui.widgets._provider_usage_indicator import usage_indicator_groups
from sase.ace.tui.widgets._text_signature import text_signature
from sase.ace.tui.widgets.provider_usage_indicator import ProviderUsageIndicator
from tests._provider_disables_indicator_helpers import (
    _FROZEN_NOW,
    _segments_with_offsets,
    _usage_entry,
)
from tests._provider_usage_indicator_presentation_helpers import _groups


_USAGE_MODULE = "sase.ace.tui.widgets.provider_usage_indicator"


class _FakeWorker:
    def __init__(self, group: str, result: object = None) -> None:
        self.group = group
        self.result = result


class _FakeStateChanged:
    def __init__(self, worker: _FakeWorker, state: WorkerState) -> None:
        self.worker = worker
        self.state = state


def _mock_usage_projection(
    monkeypatch: pytest.MonkeyPatch,
    *entries: dict[str, object],
) -> None:
    projection = SimpleNamespace(
        entries=entries or (_usage_entry(provider="grok", remaining_percent=7.0),),
        providers=(),
        generated_at=_FROZEN_NOW,
    )
    monkeypatch.setattr(
        f"{_USAGE_MODULE}.cached_usage_indicator_projection",
        lambda **_kwargs: projection,
    )
    monkeypatch.setattr(f"{_USAGE_MODULE}.usage_attention_enabled", lambda: True)


def test_build_content_renders_selected_windows() -> None:
    groups = _groups(_usage_entry(provider="grok", remaining_percent=7.0))
    text = ProviderUsageIndicator._build_content(groups, dark=True)

    assert "🛰️" in text.plain
    assert "7%" in text.plain


def test_tooltip_lists_attention_items() -> None:
    groups = usage_indicator_groups(
        (
            _usage_entry(
                provider="grok",
                remaining_percent=0.0,
                vendor_state="rejected",
                display_attention="rejected",
            ),
        ),
        dark=True,
        now=_FROZEN_NOW,
    )
    tooltip = ProviderUsageIndicator._build_tooltip(groups)

    assert tooltip is not None
    assert "GROK - Week - all (key weekly) · 0% remaining" in tooltip
    assert "Providers · Usage" in tooltip
    assert "middle dot" in tooltip
    assert "parentheses" not in tooltip
    assert "pipes" not in tooltip


def test_collector_failure_keeps_tooltip_prose_without_warning_glyph() -> None:
    groups = usage_indicator_groups(
        (
            _usage_entry(
                provider="codex",
                remaining_percent=12.0,
                collector_problem=True,
                display_attention="collection_problem",
            ),
        ),
        dark=True,
        now=_FROZEN_NOW,
    )
    tooltip = ProviderUsageIndicator._build_tooltip(groups)
    content = ProviderUsageIndicator._build_content(groups, dark=True)

    assert tooltip is not None
    assert "collector is currently failing for this provider" in tooltip
    assert "⚠" not in content.plain


def test_narrow_budget_collapses_then_wide_budget_restores_full_badge_packing() -> None:
    groups = usage_indicator_groups(
        [
            _usage_entry(provider="grok", remaining_percent=4.0),
            _usage_entry(provider="codex", remaining_percent=50.0),
            _usage_entry(provider="claude", remaining_percent=62.0),
        ],
        dark=True,
        now=_FROZEN_NOW,
    )
    full = ProviderUsageIndicator._build_content(groups, dark=True)
    narrow = ProviderUsageIndicator._build_content(
        groups, usage_budget=len(" usage 3 "), dark=True
    )
    wide_again = ProviderUsageIndicator._build_content(groups, dark=True)

    assert narrow.plain == " usage 3 "
    assert wide_again.plain == full.plain
    assert "🛰️" in full.plain and "🤖" in full.plain and "🎭" in full.plain


def test_zero_budget_stays_empty_when_groups_exist() -> None:
    groups = _groups(_usage_entry(provider="grok", remaining_percent=7.0))
    assert ProviderUsageIndicator._build_content(groups, usage_budget=0).plain == ""


def test_worker_error_releases_in_flight_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(f"{_USAGE_MODULE}.usage_attention_enabled", lambda: True)
    monkeypatch.setattr(
        f"{_USAGE_MODULE}.cached_usage_indicator_projection",
        lambda **_kwargs: SimpleNamespace(entries=(), providers=(), generated_at=100.0),
    )
    indicator = ProviderUsageIndicator()
    indicator._usage_peek_in_flight = True

    indicator.on_worker_state_changed(
        _FakeStateChanged(
            _FakeWorker(indicator_module._USAGE_PEEK_WORKER_GROUP),
            WorkerState.ERROR,
        )
    )

    assert indicator._usage_peek_in_flight is False


def test_worker_cancelled_releases_in_flight_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(f"{_USAGE_MODULE}.usage_attention_enabled", lambda: True)
    monkeypatch.setattr(
        f"{_USAGE_MODULE}.cached_usage_indicator_projection",
        lambda **_kwargs: SimpleNamespace(entries=(), providers=(), generated_at=100.0),
    )
    indicator = ProviderUsageIndicator()
    indicator._usage_peek_in_flight = True

    indicator.on_worker_state_changed(
        _FakeStateChanged(
            _FakeWorker(indicator_module._USAGE_PEEK_WORKER_GROUP),
            WorkerState.CANCELLED,
        )
    )

    assert indicator._usage_peek_in_flight is False


def test_late_worker_success_after_unmount_does_not_paint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_usage_projection(monkeypatch)
    indicator = ProviderUsageIndicator()
    indicator._usage_peek_in_flight = True
    indicator._pending_usage_token = ("pending",)
    updates: list[Text] = []
    monkeypatch.setattr(
        indicator, "update", lambda renderable: updates.append(renderable)
    )

    indicator.on_unmount()
    indicator.on_worker_state_changed(
        _FakeStateChanged(
            _FakeWorker(indicator_module._USAGE_PEEK_WORKER_GROUP),
            WorkerState.SUCCESS,
        )
    )

    assert indicator._usage_peek_in_flight is False
    assert updates == []


async def test_provider_usage_indicator_is_mounted() -> None:
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#provider-usage-indicator",
            ProviderUsageIndicator,
        )

    assert isinstance(indicator, ProviderUsageIndicator)


async def test_click_opens_provider_usage_when_groups_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _mock_usage_projection(monkeypatch)

    async with AcePage() as page:
        monkeypatch.setattr(
            page.app,
            "action_open_provider_usage",
            lambda *a, **k: calls.append("open_provider_usage"),
        )
        indicator = page.query_one_widget(
            "#provider-usage-indicator",
            ProviderUsageIndicator,
        )
        indicator.set_usage_budget(80)
        indicator._apply_content()
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await page.pause()
        event = MagicMock(
            screen_x=indicator.region.right - 1,
            screen_y=indicator.region.y,
        )
        await indicator.on_click(event)
        await page.pause()

    assert calls == ["open_provider_usage"]
    event.stop.assert_called_once()
    event.prevent_default.assert_called_once()


async def test_theme_switch_repaints_usage_gaps_with_identical_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_usage_projection(monkeypatch)
    dark_groups = usage_indicator_groups(
        [_usage_entry(provider="grok", remaining_percent=7.0)],
        dark=True,
        now=_FROZEN_NOW,
    )
    dark_reference = ProviderUsageIndicator._build_content(dark_groups, dark=True)
    assert "7%" in dark_reference.plain

    updates: list[Text] = []
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#provider-usage-indicator",
            ProviderUsageIndicator,
        )
        indicator.set_usage_budget(80)
        indicator._apply_content()
        assert indicator._content_signature == text_signature(dark_reference)

        original_update = indicator.update
        monkeypatch.setattr(
            indicator,
            "update",
            lambda renderable: (
                updates.append(renderable),
                original_update(renderable),
            )[1],
        )

        page.app.theme = "textual-light"
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await page.pause()

    assert len(updates) == 1
    repainted = updates[0]
    assert repainted.plain == dark_reference.plain
    assert _segments_with_offsets(repainted) != _segments_with_offsets(dark_reference)


async def test_unchanged_apply_content_does_not_reissue_static_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_usage_projection(monkeypatch)
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#provider-usage-indicator",
            ProviderUsageIndicator,
        )
        indicator.set_usage_budget(80)
        indicator._apply_content()

        calls: list[Text] = []
        original_update = indicator.update
        monkeypatch.setattr(
            indicator,
            "update",
            lambda renderable: (calls.append(renderable), original_update(renderable))[
                1
            ],
        )

        indicator._apply_content()
        indicator._apply_content()

    assert calls == []


async def test_initial_cache_renders_after_header_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_usage_projection(monkeypatch)
    async with AcePage(size=(120, 24)) as page:
        indicator = page.query_one_widget(
            "#provider-usage-indicator",
            ProviderUsageIndicator,
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await page.pause()

        assert "7%" in indicator.render().plain
        assert indicator.usage_open_provider == "grok"


async def test_worker_success_applies_late_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = SimpleNamespace(entries=(), providers=(), generated_at=_FROZEN_NOW)
    loaded = SimpleNamespace(
        entries=(_usage_entry(provider="grok", remaining_percent=7.0),),
        providers=(),
        generated_at=_FROZEN_NOW,
    )
    monkeypatch.setattr(f"{_USAGE_MODULE}.usage_attention_enabled", lambda: True)
    monkeypatch.setattr(
        f"{_USAGE_MODULE}.cached_usage_indicator_projection",
        lambda **_kwargs: empty,
    )
    async with AcePage(size=(120, 24)) as page:
        indicator = page.query_one_widget(
            "#provider-usage-indicator",
            ProviderUsageIndicator,
        )
        indicator.set_usage_budget(80)
        indicator._apply_content()
        assert indicator.render().plain == ""

        monkeypatch.setattr(
            f"{_USAGE_MODULE}.cached_usage_indicator_projection",
            lambda **_kwargs: loaded,
        )
        indicator._pending_usage_token = ("token",)
        indicator._usage_peek_in_flight = True
        indicator.on_worker_state_changed(
            _FakeStateChanged(
                _FakeWorker(indicator_module._USAGE_PEEK_WORKER_GROUP),
                WorkerState.SUCCESS,
            )
        )
        await page.pause()

        assert "7%" in indicator.render().plain
        assert indicator._usage_peek_loaded is True
        assert indicator._usage_peek_in_flight is False
