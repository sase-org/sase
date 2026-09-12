"""Header geometry, title priority, and usage-cluster interaction tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.widgets._header import HeaderClockSpace, HeaderIcon, HeaderTitle

from sase.ace.testing import AcePage
from sase.ace.tui.modals.models_panel_usage_modal import ProviderUsageModal
from sase.ace.tui.widgets.provider_disables_indicator import ProviderDisablesIndicator
from sase.ace.tui.widgets.provider_usage_indicator import ProviderUsageIndicator
from sase.ace.tui.widgets.usage_header import UsageHeader
from sase.llm_provider.provider_priority import provider_routing_context_from_parts
from tests._provider_disables_indicator_helpers import _disable
from tests._provider_usage_indicator_presentation_helpers import (
    FROZEN_NOW,
    _entry,
    _scope,
)

_USAGE_MODULE = "sase.ace.tui.widgets.provider_usage_indicator"
_ROUTING_MODULE = "sase.ace.tui.widgets.provider_disables_indicator"
_HEADER_WIDTHS = (60, 80, 120, 140, 160, 240)


def _projection(*entries: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(entries=entries, providers=(), generated_at=FROZEN_NOW)


def _patch_usage(
    monkeypatch: pytest.MonkeyPatch,
    *entries: dict[str, object],
) -> None:
    monkeypatch.setattr(f"{_USAGE_MODULE}.usage_attention_enabled", lambda: True)
    monkeypatch.setattr(
        f"{_USAGE_MODULE}.cached_usage_indicator_projection",
        lambda **_kwargs: _projection(*entries),
    )
    monkeypatch.setattr(
        f"{_USAGE_MODULE}.refresh_usage_peek_cache",
        lambda **_kwargs: ((), frozenset()),
    )


def _claude_windows() -> tuple[dict[str, object], ...]:
    return (
        _entry(provider="claude", window_key="weekly", remaining_percent=62.0),
        _entry(
            provider="claude",
            window_key="weekly:claude-fable-5",
            weekly_all=False,
            scope=_scope(
                kind="product", product="claude", model_ids=("claude-fable-5",)
            ),
            remaining_percent=100.0,
            seconds_until_reset=115_200.0,
            resets_at=FROZEN_NOW + 115_200.0,
        ),
        _entry(
            provider="codex",
            remaining_percent=45.0,
            seconds_until_reset=190_800.0,
            resets_at=FROZEN_NOW + 190_800.0,
        ),
    )


def _top_bar_regions(page: AcePage) -> dict[str, tuple[int, int, int, int]]:
    top_bar = page.query_one_widget("#top-bar")
    return {
        child.id: (
            child.region.x,
            child.region.y,
            child.region.width,
            child.region.height,
        )
        for child in top_bar.children
        if child.id is not None
    }


def _header_widgets(
    page: AcePage,
) -> tuple[UsageHeader, HeaderIcon, HeaderTitle, ProviderUsageIndicator]:
    header = page.app.query_one("#ace-header", UsageHeader)
    icon = page.app.query_one(HeaderIcon)
    title = page.app.query_one(HeaderTitle)
    usage = page.app.query_one("#provider-usage-indicator", ProviderUsageIndicator)
    return header, icon, title, usage


async def _settle(page: AcePage) -> None:
    page.app.refresh(layout=True)
    await page.app.wait_for_refresh()
    await page.pause()


@pytest.mark.parametrize("width", _HEADER_WIDTHS)
async def test_usage_header_keeps_title_left_and_usage_right(
    monkeypatch: pytest.MonkeyPatch,
    width: int,
) -> None:
    _patch_usage(monkeypatch, *_claude_windows())
    async with AcePage(size=(width, 24)) as page:
        await _settle(page)
        header, icon, title, usage = _header_widgets(page)

        assert header.region.height == 1
        assert page.query_one_widget("#top-bar").region.height == 1
        assert not list(header.query(HeaderClockSpace))
        assert icon.region.x == header.region.x
        assert title.region.x == icon.region.x + icon.region.width
        assert (
            usage.region.x + usage.region.width == header.region.x + header.region.width
        )
        if usage.region.width:
            assert title.region.x + title.region.width <= usage.region.x
        assert header.scroll_offset.x == 0
        assert str(page.app.title).startswith("sase ace")
        if width >= 120:
            assert "🎭" in usage.render().plain
            assert "·" in usage.render().plain or "45%" in usage.render().plain


async def test_short_and_long_titles_and_subtitles_reflow_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_usage(monkeypatch, *_claude_windows())
    async with AcePage(size=(120, 24)) as page:
        await _settle(page)
        header, icon, title, usage = _header_widgets(page)
        title_origin = title.region.x
        usage_right = usage.region.x + usage.region.width
        short_budget = usage._usage_budget

        page.app.sub_title = "workspace"
        await _settle(page)
        assert title.region.x == title_origin
        assert usage.region.x + usage.region.width == usage_right
        assert page.app.sub_title == "workspace"

        page.app.title = "sase ace (" + "v0.8.0+9.gdeadbee.dirty" + ")"
        await _settle(page)
        assert title.region.x == title_origin
        assert usage.region.x + usage.region.width == usage_right
        assert usage._usage_budget <= short_budget


async def test_late_version_title_change_shrinks_usage_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_usage(monkeypatch, *_claude_windows())
    async with AcePage(size=(80, 24)) as page:
        await _settle(page)
        _header, _icon, _title, usage = _header_widgets(page)
        before = usage._usage_budget
        page.app.title = "sase ace (v0.8.0+99.gabcdefgh.dirty-workspace)"
        await _settle(page)
        assert usage._usage_budget <= before


async def test_no_usage_keeps_title_and_empty_cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_usage(monkeypatch)
    async with AcePage(size=(80, 24)) as page:
        await _settle(page)
        header, icon, title, usage = _header_widgets(page)
        assert usage.render().plain == ""
        assert usage.region.width == 0
        assert title.region.x == icon.region.x + icon.region.width
        assert header.region.height == 1


async def test_zero_space_and_narrow_to_wide_restoration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_usage(monkeypatch, *_claude_windows())
    async with AcePage(size=(20, 24)) as page:
        await _settle(page)
        header, _icon, title, usage = _header_widgets(page)
        assert usage._usage_budget == 0
        assert usage.render().plain == ""
        assert title.tooltip
        assert header.region.height == 1
        assert header.scroll_offset.x == 0

        await page._pilot.resize_terminal(160, 24)  # noqa: SLF001
        await _settle(page)
        assert usage._usage_budget > 0
        assert "🎭" in usage.render().plain


async def test_usage_only_changes_do_not_move_control_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = [
        _entry(provider="claude", remaining_percent=100.0, seconds_until_reset=36_600.0)
    ]

    def _current_projection(**_kwargs: object) -> SimpleNamespace:
        return _projection(*current)

    monkeypatch.setattr(f"{_USAGE_MODULE}.usage_attention_enabled", lambda: True)
    monkeypatch.setattr(
        f"{_USAGE_MODULE}.cached_usage_indicator_projection",
        _current_projection,
    )
    monkeypatch.setattr(
        f"{_USAGE_MODULE}.refresh_usage_peek_cache",
        lambda **_kwargs: ((), frozenset()),
    )
    async with AcePage(size=(120, 24)) as page:
        await _settle(page)
        header, _icon, title, usage = _header_widgets(page)
        title_origin = title.region.x
        usage_right = usage.region.x + usage.region.width
        before = _top_bar_regions(page)
        header_height = header.region.height
        top_height = page.query_one_widget("#top-bar").region.height

        variants = (
            [
                _entry(
                    provider="claude",
                    remaining_percent=99.0,
                    seconds_until_reset=36_540.0,
                )
            ],
            [
                _entry(
                    provider="claude",
                    remaining_percent=62.0,
                    seconds_until_reset=36_600.0,
                ),
                _entry(
                    provider="claude",
                    window_key="weekly:claude-fable-5",
                    weekly_all=False,
                    remaining_percent=7.0,
                    scope=_scope(
                        kind="product",
                        product="claude",
                        model_ids=("claude-fable-5",),
                    ),
                ),
            ],
            [],
            [
                _entry(
                    provider="grok",
                    remaining_percent=4.0,
                    display_attention="rejected",
                )
            ],
        )
        for entries in variants:
            current.clear()
            current.extend(entries)
            usage._apply_content(now=FROZEN_NOW)
            await _settle(page)
            assert _top_bar_regions(page) == before
            assert title.region.x == title_origin
            assert header.region.height == header_height == 1
            assert page.query_one_widget("#top-bar").region.height == top_height == 1
            if usage.region.width:
                assert usage.region.x + usage.region.width == usage_right


async def test_pilot_clicks_open_usage_without_expanding_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_usage(monkeypatch, *_claude_windows())
    async with AcePage(size=(160, 24)) as page:
        await _settle(page)
        header, _icon, _title, usage = _header_widgets(page)
        assert usage.region.width > 0
        assert await page._pilot.click(usage, offset=(1, 0))  # noqa: SLF001
        await page.pause()
        await page.expect_modal("ProviderUsageModal")
        assert not header.has_class("-tall")
        modal = page.app.screen
        assert isinstance(modal, ProviderUsageModal)
        assert modal._initial_provider == "claude"
        await page.press("escape")
        await page.expect_no_modal()

        assert await page._pilot.click(
            usage, offset=(max(0, usage.region.width - 2), 0)
        )  # noqa: SLF001
        await page.pause()
        await page.expect_modal("ProviderUsageModal")
        assert not header.has_class("-tall")
        await page.press("escape")
        await page.expect_no_modal()


async def test_fallback_clicks_open_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_usage(
        monkeypatch,
        *(_entry(provider=f"p{index}", remaining_percent=62.0) for index in range(8)),
    )
    async with AcePage(size=(40, 24)) as page:
        await _settle(page)
        _header, _icon, title, usage = _header_widgets(page)
        page.app.title = "sase ace " + ("n" * 24)
        await _settle(page)
        rendered = usage.render().plain.strip()
        assert (
            rendered in {"usage 8", "8", "…"}
            or "🎭" in usage.render().plain
            or rendered == ""
        )
        if usage.region.width:
            await page.click("#provider-usage-indicator")
            await page.expect_modal("ProviderUsageModal")
            assert not page.app.query_one("#ace-header", UsageHeader).has_class("-tall")
            await page.press("escape")
            await page.expect_no_modal()
        page.app.action_open_provider_usage()
        await page.expect_modal("ProviderUsageModal")


async def test_routing_click_stays_on_launch_with_usage_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_usage(monkeypatch, *_claude_windows())
    monkeypatch.setattr(
        f"{_ROUTING_MODULE}.peek_provider_routing_context",
        lambda *a, **k: provider_routing_context_from_parts(
            {"claude": _disable("claude", expires_at=None)},
            None,
            captured_at=100.0,
        ),
    )
    calls: list[str] = []
    async with AcePage(size=(160, 24)) as page:
        monkeypatch.setattr(
            page.app,
            "_open_models_panel",
            lambda: calls.append("launch"),
        )
        await _settle(page)
        routing = page.app.query_one(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
        assert "CLAUDE" in routing.render().plain
        await page.click("#provider-disables-indicator")
        await page.pause()
        assert calls == ["launch"]
        assert page.state["modal"] is None


async def test_header_icon_keeps_hit_target_and_palette_works_at_zero_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_usage(monkeypatch, *_claude_windows())
    async with AcePage(size=(20, 24)) as page:
        await _settle(page)
        _header, icon, _title, usage = _header_widgets(page)
        assert icon.region.width == 8
        assert usage._usage_budget == 0
        page.app.action_open_command_palette()
        await page.expect_modal("CommandPaletteModal")
        await page.press("escape")
        await page.expect_no_modal()
        page.app.action_open_provider_usage()
        await page.expect_modal("ProviderUsageModal")


async def test_explicit_provider_argument_wins_over_header_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_usage(monkeypatch, *_claude_windows())
    async with AcePage(size=(120, 24)) as page:
        await _settle(page)
        page.app.action_open_provider_usage("codex")
        await page.expect_modal("ProviderUsageModal")
        modal = page.app.screen
        assert isinstance(modal, ProviderUsageModal)
        assert modal._initial_provider == "codex"


async def test_unused_header_space_still_expands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_usage(monkeypatch)
    async with AcePage(size=(120, 24)) as page:
        await _settle(page)
        header, _icon, title, usage = _header_widgets(page)
        assert usage.region.width == 0
        assert title.region.width > 1
        # Click the title widget so the event bubbles into Header. Textual
        # dispatches every matching MRO handler; a subclass `_on_click` would
        # toggle `-tall` twice and cancel expansion.
        assert await page._pilot.click(  # noqa: SLF001
            title, offset=(max(0, title.region.width // 2), 0)
        )
        await _settle(page)
        assert header.has_class("-tall")
        assert header.region.height == 3
