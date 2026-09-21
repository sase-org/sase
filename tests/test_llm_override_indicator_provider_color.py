"""Provider-hue rendering tests for the calm launch-default pill."""

from __future__ import annotations

import threading

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.provider_styles import provider_text_palette
from sase.ace.tui.widgets import launch_context_source as source_module
from sase.ace.tui.widgets import llm_override_indicator as indicator_module
from sase.ace.tui.widgets._override_pill import build_calm_default_pill
from sase.ace.tui.widgets.llm_override_indicator import LLMOverrideIndicator
from sase.llm_provider.model_launch_settings import (
    DEFAULT_MODEL_FIELD,
    LaunchModelSettingSnapshot,
    launch_model_setting_override_key,
)
from sase.llm_provider.temporary_override import TemporaryLLMOverride

_NEUTRAL_STYLE = "dim cyan"


@pytest.fixture(autouse=True)
def _bare_directive_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the pill subject to the bare model name, independent of plugins."""
    for module in (indicator_module, source_module):
        monkeypatch.setattr(
            module,
            "format_model_directive_label",
            lambda provider=None, model=None: model or "",
        )


def _resolved(
    provider: str,
    model: str,
    *,
    effort: str | None = "high",
    with_palette: bool = True,
) -> LLMOverrideIndicator:
    """Return an indicator whose cached launch default is already resolved."""
    indicator = LLMOverrideIndicator()
    indicator._cached_default = (provider, model)
    indicator._cached_snapshot = source_module.LaunchDefaultSnapshot(
        provider=provider,
        model=model,
        referenced_alias=None,
        selector_mode=None,
        member_count=0,
        effort=effort,
        directive_label=model,
        palette=provider_text_palette(provider) if with_palette else None,
    )
    return indicator


def _segments(text: Text) -> list[tuple[str, str]]:
    return [(text.plain[span.start : span.end], str(span.style)) for span in text.spans]


def test_calm_pill_paints_subject_and_effort_in_the_provider_hues() -> None:
    palette = provider_text_palette("grok")

    text = _resolved("grok", "grok-4.6")._build_cached_default_content()

    assert text.plain == " grok-4.6@high "
    assert text.style == palette.subject_style
    assert ("@high", palette.detail_style) in _segments(text)


def test_calm_pill_without_effort_has_no_detail_span() -> None:
    palette = provider_text_palette("claude")

    text = _resolved("claude", "opus-5", effort=None)._build_cached_default_content()

    assert text.plain == " opus-5 "
    assert text.style == palette.subject_style
    assert all(style != palette.detail_style for _, style in _segments(text))


def test_calm_pill_width_matches_the_uncolored_label() -> None:
    text = _resolved("codex", "o3")._build_cached_default_content()

    assert text.cell_len == len(" o3@high ")


def test_two_providers_yield_two_pill_subject_styles_for_one_model_name() -> None:
    claude = _resolved("claude", "shared-model")._build_cached_default_content()
    grok = _resolved("grok", "shared-model")._build_cached_default_content()

    assert claude.plain == grok.plain
    assert claude.style != grok.style
    assert _segments(claude) != _segments(grok)


def test_build_calm_default_pill_mirrors_the_override_pill_grammar() -> None:
    palette = provider_text_palette("codex")

    text = build_calm_default_pill(subject="o3", effort="max", palette=palette)

    assert text.plain == " o3@max "
    assert text.style == palette.subject_style
    assert _segments(text) == [
        ("@max", palette.detail_style),
        (" ", palette.subject_style),
    ]


def test_cached_pill_renders_from_the_cached_palette_without_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indicator = _resolved("codex", "o3")

    def fail_palette(provider: str | None) -> object:
        raise AssertionError("render path must not resolve a palette")

    monkeypatch.setattr(indicator_module, "provider_text_palette", fail_palette)

    text = indicator._build_cached_default_content()

    assert text.plain == " o3@high "
    assert text.style == provider_text_palette("codex").subject_style


def test_snapshot_without_a_palette_renders_the_neutral_pill() -> None:
    text = _resolved("codex", "o3", with_palette=False)._build_cached_default_content()

    assert text.plain == " o3@high "
    assert text.style == _NEUTRAL_STYLE
    assert all(style == _NEUTRAL_STYLE for _, style in _segments(text))


def test_cached_default_without_a_snapshot_renders_the_neutral_pill() -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("codex", "o3")
    indicator._cached_snapshot = None

    text = indicator._build_cached_default_content()

    assert text.plain == " CODEX(o3) "
    assert text.style == _NEUTRAL_STYLE


def test_unresolved_states_never_guess_a_provider_hue() -> None:
    placeholder = LLMOverrideIndicator()._build_cached_default_content()
    failed = LLMOverrideIndicator()
    failed._cached_default_failed = True

    assert placeholder.plain == " ... "
    assert placeholder.style == _NEUTRAL_STYLE
    assert failed._build_cached_default_content().plain == " unavailable "
    assert failed._build_cached_default_content().style == _NEUTRAL_STYLE


def test_synchronous_default_content_palette_failure_degrades_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_palette(provider: str | None) -> object:
        raise RuntimeError("palette failed")

    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot("codex", "o3"),
    )
    monkeypatch.setattr(indicator_module, "provider_text_palette", fail_palette)

    text = LLMOverrideIndicator._build_default_content()

    assert text.plain == " unavailable "
    assert text.style == _NEUTRAL_STYLE


def test_gold_override_pill_styles_are_unchanged() -> None:
    override = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="codex/o3",
        created_at=100.0,
        expires_at=3_820.0,
        source="test",
        effort="medium",
    )

    text = LLMOverrideIndicator._build_content(override, now=100.0)

    assert text.plain == " CODEX(o3)@medium 1h2m "
    assert str(text.style) == "bold #1a1a1a on #D7AF5F"
    assert _segments(text) == [
        ("@medium", "not bold #4F3D18 on #D7AF5F"),
        (" 1h2m ", "not bold #4F3D18 on #D7AF5F"),
    ]


async def test_worker_resolves_the_palette_off_the_ui_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The palette rides the worker's snapshot; the UI thread never builds it."""
    ui_thread = threading.get_ident()
    palette_threads: list[int] = []

    def recording_palette(provider: str | None):
        palette_threads.append(threading.get_ident())
        return provider_text_palette(provider)

    monkeypatch.setattr(
        source_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot("claude", "sonnet"),
    )
    monkeypatch.setattr(source_module, "provider_text_palette", recording_palette)

    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#llm-override-indicator", LLMOverrideIndicator
        )
        await page.wait_for(lambda _state: indicator._cached_snapshot is not None)
        snapshot = indicator._cached_snapshot
        rendered = indicator._build_cached_default_content()

    assert snapshot is not None
    assert snapshot.palette == provider_text_palette("claude")
    assert palette_threads
    assert ui_thread not in palette_threads
    assert rendered.style == provider_text_palette("claude").subject_style


def _snapshot(provider: str, model: str) -> LaunchModelSettingSnapshot:
    return LaunchModelSettingSnapshot(
        field=DEFAULT_MODEL_FIELD,
        config_path="llm_provider.default_model",
        raw_value=f"{provider}/{model}",
        provider=provider,
        model=model,
        effort=None,
        provenance="configured",
        referenced_alias=None,
        override_key=launch_model_setting_override_key(DEFAULT_MODEL_FIELD),
    )
