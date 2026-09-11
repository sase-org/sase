"""ProviderDisablesIndicator widget lifecycle tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.widgets._provider_usage_indicator import usage_indicator_badges
from sase.ace.tui.widgets.provider_disables_indicator import (
    ProviderDisablesIndicator,
    _text_signature,
)
from sase.llm_provider.provider_priority import provider_routing_context_from_parts
from tests._provider_disables_indicator_helpers import (
    _FROZEN_NOW,
    _MODULE,
    _disable,
    _mock_usage_projection,
    _segments_with_offsets,
    _usage_entry,
)


def test_initial_content_uses_peek_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    context = provider_routing_context_from_parts(
        {"claude": _disable(expires_at=None)},
        None,
        captured_at=100.0,
    )
    peek = MagicMock(return_value=context)
    monkeypatch.setattr(f"{_MODULE}.peek_provider_routing_context", peek)
    monkeypatch.setattr(
        f"{_MODULE}.cached_usage_indicator_projection",
        lambda **_kwargs: SimpleNamespace(
            entries=(),
            providers=(),
            generated_at=100.0,
        ),
    )

    rendered = ProviderDisablesIndicator()._build_initial_content()

    assert isinstance(rendered, Text)
    assert rendered.plain == " CLAUDE off ∞ "
    peek.assert_called()


async def test_provider_disables_indicator_is_mounted() -> None:
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )

    assert isinstance(indicator, ProviderDisablesIndicator)


async def test_click_opens_models_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async with AcePage() as page:
        monkeypatch.setattr(
            page.app,
            "_open_models_panel",
            lambda: calls.append("opened"),
        )
        indicator = page.query_one_widget(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
        indicator._usage_open_provider = None
        await indicator.on_click()
        await page.pause()

    assert calls == ["opened"]


async def test_click_opens_provider_usage_when_attention_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async with AcePage() as page:

        async def _run_action(action: str, *args: object, **kwargs: object) -> None:
            calls.append(action)

        monkeypatch.setattr(page.app, "run_action", _run_action)
        indicator = page.query_one_widget(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
        indicator._usage_open_provider = "grok"
        await indicator.on_click()
        await page.pause()

    assert calls == ["open_provider_usage"]


def test_text_signature_changes_when_only_the_base_style_changes() -> None:
    dark_text = Text("usage 3", style="bold #B8C0CC on #242830")
    light_text = Text("usage 3", style="bold #4B535F on #E0E0E0")

    assert dark_text.plain == light_text.plain
    assert dark_text.spans == light_text.spans == []
    assert _text_signature(dark_text) != _text_signature(light_text)


async def test_theme_switch_repaints_usage_gaps_with_identical_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_usage_projection(monkeypatch)
    dark_badges = usage_indicator_badges(
        [_usage_entry(provider="grok", remaining_percent=7.0)],
        dark=True,
        now=_FROZEN_NOW,
    )
    dark_reference = ProviderDisablesIndicator._build_content(
        {}, usage_badges=dark_badges, dark=True, now=100.0
    )
    assert "7%" in dark_reference.plain

    updates: list[Text] = []
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
        indicator._apply_content()
        assert indicator._content_signature == _text_signature(dark_reference)

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
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
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
