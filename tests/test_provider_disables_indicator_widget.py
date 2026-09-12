"""ProviderDisablesIndicator widget lifecycle tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.provider_disables_indicator import (
    ProviderDisablesIndicator,
    _text_signature,
)
from sase.llm_provider.provider_priority import provider_routing_context_from_parts
from tests._provider_disables_indicator_helpers import (
    _MODULE,
    _disable,
)


def test_initial_content_uses_peek_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    context = provider_routing_context_from_parts(
        {"claude": _disable(expires_at=None)},
        None,
        captured_at=100.0,
    )
    peek = MagicMock(return_value=context)
    monkeypatch.setattr(f"{_MODULE}.peek_provider_routing_context", peek)

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
        await indicator.on_click()
        await page.pause()

    assert calls == ["opened"]


def test_text_signature_changes_when_only_the_base_style_changes() -> None:
    dark_text = Text("usage 3", style="bold #B8C0CC on #242830")
    light_text = Text("usage 3", style="bold #4B535F on #E0E0E0")

    assert dark_text.plain == light_text.plain
    assert dark_text.spans == light_text.spans == []
    assert _text_signature(dark_text) != _text_signature(light_text)


async def test_unchanged_apply_content_does_not_reissue_static_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = provider_routing_context_from_parts({}, None, captured_at=100.0)
    monkeypatch.setattr(
        f"{_MODULE}.peek_provider_routing_context",
        lambda *a, **k: context,
    )
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
