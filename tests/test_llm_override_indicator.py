"""Tests for the LLMOverrideIndicator widget rendering."""

from __future__ import annotations

import json
import time

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.provider_styles import provider_text_palette
from sase.ace.tui.widgets import launch_context_source as source_module
from sase.ace.tui.widgets import llm_override_indicator as indicator_module
from sase.ace.tui.widgets._override_pill import format_remaining_until
from sase.ace.tui.widgets.llm_override_indicator import LLMOverrideIndicator
from sase.llm_provider.model_launch_settings import (
    DEFAULT_MODEL_FIELD,
    LaunchModelSettingSnapshot,
    launch_model_setting_override_key,
)
from sase.llm_provider.temporary_override import TemporaryLLMOverride
from sase.llm_provider.temporary_override_state import state_path


def _snapshot(
    *,
    provider: str = "claude",
    model: str = "opus",
    effort: str | None = None,
    referenced_alias: str | None = None,
    selector_mode: str | None = None,
    selector_members: tuple = (),
) -> LaunchModelSettingSnapshot:
    """Build a minimal launch-model setting snapshot for resolver stubs."""
    return LaunchModelSettingSnapshot(
        field=DEFAULT_MODEL_FIELD,
        config_path="llm_provider.default_model",
        raw_value=f"{provider}/{model}",
        provider=provider,
        model=model,
        effort=effort,
        provenance="configured",
        referenced_alias=referenced_alias,
        override_key=launch_model_setting_override_key(DEFAULT_MODEL_FIELD),
        selector_mode=selector_mode,
        selector_members=selector_members,
    )


@pytest.fixture(autouse=True)
def _bare_directive_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the pill subject to the bare model name, independent of plugins.

    The real formatter consults installed provider plugins' model metadata;
    tests that care about a specific spelling re-patch it themselves.
    """
    for module in (indicator_module, source_module):
        monkeypatch.setattr(
            module,
            "format_model_directive_label",
            lambda provider=None, model=None: model or "",
        )


def _override(
    *,
    provider: str = "codex",
    model: str = "o3",
    expires_at: float | None = 1_000.0,
    effort: str | None = None,
) -> TemporaryLLMOverride:
    """Build a test override."""
    return TemporaryLLMOverride(
        provider=provider,
        model=model,
        raw_model=f"{provider}/{model}",
        created_at=100.0,
        expires_at=expires_at,
        source="test",
        effort=effort,
    )


def test_inactive_renders_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="codex", model="gpt-5.6-sol"),
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == "gpt-5.6-sol"
    assert text.style == provider_text_palette("codex").subject_style


def test_active_override_skips_default_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> LaunchModelSettingSnapshot:
        raise AssertionError("default resolver should not be called")

    monkeypatch.setattr(indicator_module, "build_launch_model_setting_snapshot", fail)

    text = LLMOverrideIndicator._build_content(_override(expires_at=3_820.0), now=100.0)

    assert text.plain == "CODEX(o3) 1h2m"


def test_active_with_expiry_renders_label_and_countdown() -> None:
    text = LLMOverrideIndicator._build_content(_override(expires_at=3_820.0), now=100.0)

    assert text.plain == "CODEX(o3) 1h2m"
    assert "#D7AF5F" in str(text.style)


def test_active_override_renders_effort() -> None:
    text = LLMOverrideIndicator._build_content(
        _override(expires_at=3_820.0, effort="medium"),
        now=100.0,
    )

    assert text.plain == "CODEX(o3)@medium 1h2m"
    assert str(text.style) == "bold #1a1a1a on #D7AF5F"
    styled_segments = [
        (text.plain[span.start : span.end], str(span.style)) for span in text.spans
    ]
    assert ("@medium", "not bold #4F3D18 on #D7AF5F") in styled_segments
    assert (" 1h2m", "not bold #4F3D18 on #D7AF5F") in styled_segments


def test_active_until_cleared_renders_without_countdown() -> None:
    text = LLMOverrideIndicator._build_content(_override(expires_at=None), now=100.0)

    assert text.plain == "CODEX(o3) ∞"


def test_expired_override_renders_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="claude", model="sonnet"),
    )

    text = LLMOverrideIndicator._build_content(_override(expires_at=99.0), now=100.0)

    assert text.plain == "sonnet"


def test_expired_state_file_is_cleaned_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="claude", model="sonnet"),
    )
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "provider": "codex",
                "model": "o3",
                "raw_model": "codex/o3",
                "created_at": time.time() - 120,
                "expires_at": time.time() - 60,
                "source": "test",
            }
        ),
        encoding="utf-8",
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == "sonnet"
    assert not path.exists()


def test_long_override_label_renders_fully() -> None:
    text = LLMOverrideIndicator._build_content(
        _override(provider="verylongprovider", model="extremely-long-model-name"),
        now=100.0,
    )

    assert text.plain == "VERYLONGPROVIDER(extremely-long-model-name) 15m"


def test_long_default_label_renders_fully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(
            provider="verylongprovider", model="extremely-long-model-name"
        ),
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == "extremely-long-model-name"


def test_default_resolution_failure_renders_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> LaunchModelSettingSnapshot:
        raise RuntimeError("no provider")

    monkeypatch.setattr(indicator_module, "build_launch_model_setting_snapshot", fail)

    text = LLMOverrideIndicator._build_content()

    assert text.plain == "unavailable"


def test_remaining_subminute_rounds_up_to_one_minute() -> None:
    assert format_remaining_until(130.0, now=100.0) == "1m"


def test_remaining_multi_day_renders_day_and_hour_unit() -> None:
    remaining = 3 * 86400 + 4 * 3600
    assert format_remaining_until(100.0 + remaining, now=100.0) == "3d4h"


def test_remaining_exact_days_renders_day_unit_only() -> None:
    remaining = 2 * 86400
    assert format_remaining_until(100.0 + remaining, now=100.0) == "2d"


def test_tooltip_describes_inactive_default_states() -> None:
    indicator = LLMOverrideIndicator()

    assert indicator._build_tooltip(None) == (
        "Launch default: resolving…\n"
        "The model and effort a new agent uses when its prompt "
        "sets no %model or %effort.\n"
        "Click (or ,m) to change it in Config › Launch."
    )

    indicator._cached_default = ("claude", "opus")
    assert indicator._build_tooltip(None).startswith("Launch default: CLAUDE(opus)\n")

    indicator._cached_default = None
    indicator._cached_default_failed = True
    assert indicator._build_tooltip(None).startswith("Launch default: unavailable\n")


def test_tooltip_describes_active_override_with_effort_and_expiry() -> None:
    indicator = LLMOverrideIndicator()

    tooltip = indicator._build_tooltip(
        _override(
            provider="claude",
            model="opus",
            effort="xhigh",
            expires_at=3_820.0,
        ),
        now=100.0,
    )

    assert tooltip == (
        "Temporary override: CLAUDE(opus) @ xhigh · 1h2m left\n"
        "New agents use this instead of the launch default until it lapses.\n"
        "Click (or ,m) to change or clear it in Config › Launch."
    )


def test_tooltip_describes_until_cleared_override() -> None:
    indicator = LLMOverrideIndicator()

    tooltip = indicator._build_tooltip(_override(expires_at=None), now=100.0)

    assert tooltip == (
        "Temporary override: CODEX(o3) · until cleared\n"
        "New agents use this instead of the launch default until it lapses.\n"
        "Click (or ,m) to change or clear it in Config › Launch."
    )


async def test_llm_override_indicator_is_mounted() -> None:
    async with AcePage() as page:
        indicator = page.app.query(LLMOverrideIndicator).first()

    assert isinstance(indicator, LLMOverrideIndicator)


def test_init_skips_cold_default_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """``__init__`` must not resolve launch defaults or effort on the UI thread."""

    def fail_snapshot(*args: object, **kwargs: object) -> LaunchModelSettingSnapshot:
        raise AssertionError("default resolver should not be called during init")

    def fail_effort(*args: object, **kwargs: object) -> tuple[str | None, bool]:
        raise AssertionError("effort resolver should not be called during init")

    monkeypatch.setattr(
        indicator_module, "build_launch_model_setting_snapshot", fail_snapshot
    )
    monkeypatch.setattr(indicator_module, "resolve_effective_effort", fail_effort)

    indicator = LLMOverrideIndicator()

    rendered = indicator._build_initial_content()
    assert isinstance(rendered, Text)
    assert rendered.plain == "..."
    assert "cyan" in str(rendered.style)
    assert indicator._cached_default is None
    assert indicator._cached_default_failed is False


async def test_click_opens_models_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async with AcePage() as page:
        monkeypatch.setattr(
            page.app,
            "_open_models_panel",
            lambda: calls.append("opened"),
        )
        indicator = page.app.query(LLMOverrideIndicator).first()
        await indicator.on_click()
        await page.pause()

    assert calls == ["opened"]


def test_tooltip_adds_rotation_line_for_round_robin_pool() -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("claude", "opus")
    indicator._cached_snapshot = source_module.LaunchDefaultSnapshot(
        provider="claude",
        model="opus",
        referenced_alias="large",
        selector_mode="round_robin",
        member_count=2,
    )

    tooltip = indicator._build_tooltip(None)

    assert tooltip == (
        "Launch default: CLAUDE(opus)\n"
        "@large rotates across 2 models; CLAUDE(opus) is next.\n"
        "The model and effort a new agent uses when its prompt "
        "sets no %model or %effort.\n"
        "Click (or ,m) to change it in Config › Launch."
    )


def test_tooltip_omits_rotation_line_for_non_pool_default() -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("claude", "opus")
    indicator._cached_snapshot = source_module.LaunchDefaultSnapshot(
        provider="claude",
        model="opus",
        referenced_alias=None,
        selector_mode=None,
        member_count=0,
    )

    tooltip = indicator._build_tooltip(None)

    assert tooltip == (
        "Launch default: CLAUDE(opus)\n"
        "The model and effort a new agent uses when its prompt "
        "sets no %model or %effort.\n"
        "Click (or ,m) to change it in Config › Launch."
    )


def test_calm_default_renders_configured_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.llm_provider.config._get_default_effort", lambda: "high")
    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="codex", model="o3"),
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == "o3@high"
    assert text.style == provider_text_palette("codex").subject_style


def test_alias_borne_effort_wins_over_configured_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.llm_provider.config._get_default_effort", lambda: "high")
    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="codex", model="o3", effort="medium"),
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == "o3@medium"


def test_temporary_effort_override_wins_over_configured_and_loses_to_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider.effort_override import TemporaryEffortOverride

    override = TemporaryEffortOverride(
        version=1,
        effort="low",
        created_at=1.0,
        expires_at=None,
        source="test",
    )
    monkeypatch.setattr("sase.llm_provider.config._get_default_effort", lambda: "high")
    monkeypatch.setattr(
        "sase.llm_provider.config._get_temporary_default_effort",
        lambda now: override,
    )
    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="codex", model="o3"),
    )

    text = LLMOverrideIndicator._build_content()
    assert text.plain == "o3@low"

    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="codex", model="o3", effort="medium"),
    )
    text = LLMOverrideIndicator._build_content()
    assert text.plain == "o3@medium"


def test_configured_none_renders_none_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.llm_provider.config._get_default_effort", lambda: "none")
    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="codex", model="o3"),
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == "o3@none"


def test_tooltip_includes_effort_and_round_robin_keeps_suffix() -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("claude", "opus")
    indicator._cached_snapshot = source_module.LaunchDefaultSnapshot(
        provider="claude",
        model="opus",
        referenced_alias="large",
        selector_mode="round_robin",
        member_count=2,
        effort="high",
    )

    tooltip = indicator._build_tooltip(None)

    assert tooltip == (
        "Launch default: CLAUDE(opus) @ high\n"
        "@large rotates across 2 models; CLAUDE(opus) is next.\n"
        "The model and effort a new agent uses when its prompt "
        "sets no %model or %effort.\n"
        "Click (or ,m) to change it in Config › Launch."
    )


def test_cached_default_content_appends_effort() -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("codex", "o3")
    indicator._cached_snapshot = source_module.LaunchDefaultSnapshot(
        provider="codex",
        model="o3",
        referenced_alias=None,
        selector_mode=None,
        member_count=0,
        effort="high",
        directive_label="o3",
        palette=provider_text_palette("codex"),
    )

    text = indicator._build_cached_default_content()

    assert text.plain == "o3@high"
    assert text.style == provider_text_palette("codex").subject_style


def test_pill_uses_bare_directive_label_while_tooltip_keeps_provider_form() -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("claude", "opus")
    indicator._cached_snapshot = source_module.LaunchDefaultSnapshot(
        provider="claude",
        model="opus",
        referenced_alias=None,
        selector_mode=None,
        member_count=0,
        effort="high",
        directive_label="opus",
    )

    assert indicator._build_cached_default_content().plain == "opus@high"
    assert indicator._build_tooltip(None).startswith(
        "Launch default: CLAUDE(opus) @ high\n"
    )


def test_pill_renders_explicit_directive_label_verbatim() -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("codex", "o3")
    indicator._cached_snapshot = source_module.LaunchDefaultSnapshot(
        provider="codex",
        model="o3",
        referenced_alias=None,
        selector_mode=None,
        member_count=0,
        effort="high",
        directive_label="codex/o3",
    )

    assert indicator._build_cached_default_content().plain == "codex/o3@high"
    assert indicator._build_tooltip(None).startswith(
        "Launch default: CODEX(o3) @ high\n"
    )


@pytest.mark.parametrize("snapshot_present", [True, False])
def test_cached_default_without_directive_label_falls_back_to_provider_label(
    snapshot_present: bool,
) -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("claude", "opus")
    if snapshot_present:
        indicator._cached_snapshot = source_module.LaunchDefaultSnapshot(
            provider="claude",
            model="opus",
            referenced_alias=None,
            selector_mode=None,
            member_count=0,
            directive_label=None,
        )

    assert indicator._build_cached_default_content().plain == "CLAUDE(opus)"


def test_render_paths_never_call_directive_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The formatter probes plugin metadata, so it must stay off the UI thread."""

    def fail(*args: object, **kwargs: object) -> str:
        raise AssertionError("directive formatter must not run on the UI thread")

    monkeypatch.setattr(indicator_module, "format_model_directive_label", fail)
    monkeypatch.setattr(
        indicator_module, "peek_active_temporary_override", lambda *a, **k: None
    )
    indicator = LLMOverrideIndicator()
    # Unmounted: rendering via Widget.update() needs app.console, so stub it
    # to exercise the render-only refresh path without a live AcePage.
    monkeypatch.setattr(indicator, "update", lambda *a, **k: None)
    indicator._cached_default = ("claude", "opus")
    indicator._cached_default_token = ("token-a",)
    indicator._cached_snapshot = source_module.LaunchDefaultSnapshot(
        provider="claude",
        model="opus",
        referenced_alias=None,
        selector_mode=None,
        member_count=0,
        directive_label="opus",
    )

    indicator.refresh()

    assert indicator._build_initial_content().plain == "opus"
    assert indicator._build_cached_default_content().plain == "opus"


def test_default_content_formatter_failure_renders_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> str:
        raise RuntimeError("formatter exploded")

    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="codex", model="o3"),
    )
    monkeypatch.setattr(indicator_module, "format_model_directive_label", fail)

    assert LLMOverrideIndicator._build_content().plain == "unavailable"
