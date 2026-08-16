"""Tests for the LLMOverrideIndicator widget rendering."""

from __future__ import annotations

import json
import time

import pytest
from rich.text import Text
from textual.worker import WorkerState

from sase.ace.testing import AcePage
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
        effort=None,
        provenance="configured",
        referenced_alias=referenced_alias,
        override_key=launch_model_setting_override_key(DEFAULT_MODEL_FIELD),
        selector_mode=selector_mode,
        selector_members=selector_members,
    )


class _FakeWorker:
    """Duck-typed stand-in for ``textual.worker.Worker`` in unit tests."""

    def __init__(self, group: str, result: object) -> None:
        self.group = group
        self.result = result


class _FakeStateChanged:
    """Duck-typed stand-in for ``Worker.StateChanged`` in unit tests."""

    def __init__(self, worker: _FakeWorker, state: WorkerState) -> None:
        self.worker = worker
        self.state = state


def _prepare_indicator(
    monkeypatch: pytest.MonkeyPatch,
    *,
    override: TemporaryLLMOverride | None = None,
    token: tuple[object, ...] = ("token-0",),
) -> tuple[LLMOverrideIndicator, list[object]]:
    """Build an unmounted indicator with worker spawning stubbed out.

    ``run_worker`` requires an active Textual app, which these synchronous
    unit tests do not mount. Stubbing it lets tests assert *whether* a
    re-resolve was scheduled without needing a live worker thread.
    """
    monkeypatch.setattr(
        indicator_module, "peek_active_temporary_override", lambda *a, **k: override
    )
    monkeypatch.setattr(
        indicator_module, "peek_launch_default_change_token", lambda: token
    )
    indicator = LLMOverrideIndicator()
    scheduled: list[object] = []
    monkeypatch.setattr(
        indicator, "run_worker", lambda task, **kwargs: scheduled.append(task)
    )
    # These are unmounted widgets (no active Textual app): rendering via
    # Widget.update() requires app.console, which only exists once mounted.
    # Stub it out so tests can exercise the real re-arm/gating logic in
    # refresh() and on_worker_state_changed() without a live AcePage.
    monkeypatch.setattr(indicator, "update", lambda *a, **k: None)
    return indicator, scheduled


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
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        lambda: ("codex", "gpt-5.6-sol"),
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == " CODEX(gpt-5.6-sol) "
    assert "cyan" in str(text.style)


def test_active_override_skips_default_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> tuple[str, str]:
        raise AssertionError("default resolver should not be called")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        fail,
    )

    text = LLMOverrideIndicator._build_content(_override(expires_at=3_820.0), now=100.0)

    assert text.plain == " CODEX(o3) 1h2m "


def test_active_with_expiry_renders_label_and_countdown() -> None:
    text = LLMOverrideIndicator._build_content(_override(expires_at=3_820.0), now=100.0)

    assert text.plain == " CODEX(o3) 1h2m "
    assert "#D7AF5F" in str(text.style)


def test_active_override_renders_effort() -> None:
    text = LLMOverrideIndicator._build_content(
        _override(expires_at=3_820.0, effort="medium"),
        now=100.0,
    )

    assert text.plain == " CODEX(o3)@medium 1h2m "
    assert str(text.style) == "bold #1a1a1a on #D7AF5F"
    styled_segments = [
        (text.plain[span.start : span.end], str(span.style)) for span in text.spans
    ]
    assert ("@medium", "not bold #4F3D18 on #D7AF5F") in styled_segments
    assert (" 1h2m ", "not bold #4F3D18 on #D7AF5F") in styled_segments


def test_active_until_cleared_renders_without_countdown() -> None:
    text = LLMOverrideIndicator._build_content(_override(expires_at=None), now=100.0)

    assert text.plain == " CODEX(o3) ∞ "


def test_expired_override_renders_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        lambda: ("claude", "sonnet"),
    )

    text = LLMOverrideIndicator._build_content(_override(expires_at=99.0), now=100.0)

    assert text.plain == " CLAUDE(sonnet) "


def test_expired_state_file_is_cleaned_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        lambda: ("claude", "sonnet"),
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

    assert text.plain == " CLAUDE(sonnet) "
    assert not path.exists()


def test_long_override_label_renders_fully() -> None:
    text = LLMOverrideIndicator._build_content(
        _override(provider="verylongprovider", model="extremely-long-model-name"),
        now=100.0,
    )

    assert text.plain == " VERYLONGPROVIDER(extremely-long-model-name) 15m "


def test_long_default_label_renders_fully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        lambda: ("verylongprovider", "extremely-long-model-name"),
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == " VERYLONGPROVIDER(extremely-long-model-name) "


def test_default_resolution_failure_renders_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> tuple[str, str]:
        raise RuntimeError("no provider")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        fail,
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == " unavailable "


def test_remaining_subminute_rounds_up_to_one_minute() -> None:
    assert format_remaining_until(130.0, now=100.0) == "1m"


def test_tooltip_describes_inactive_default_states() -> None:
    indicator = LLMOverrideIndicator()

    assert indicator._build_tooltip(None) == (
        "Launch default: resolving...\n"
        "No temporary override active.\n"
        "Press ,m for Launch Control."
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
        "Temporary override on launch default\n"
        "CLAUDE(opus) @ xhigh\n"
        "1h2m left\n"
        "Press ,m for Launch Control."
    )


def test_tooltip_describes_until_cleared_override() -> None:
    indicator = LLMOverrideIndicator()

    tooltip = indicator._build_tooltip(_override(expires_at=None), now=100.0)

    assert tooltip == (
        "Temporary override on launch default\n"
        "CODEX(o3)\n"
        "Until cleared\n"
        "Press ,m for Launch Control."
    )


async def test_llm_override_indicator_is_mounted() -> None:
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#llm-override-indicator", LLMOverrideIndicator
        )

    assert isinstance(indicator, LLMOverrideIndicator)


def test_init_skips_cold_default_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """``__init__`` must not trigger ``resolve_effective_default_provider_model``."""

    def fail() -> tuple[str, str]:
        raise AssertionError("default resolver should not be called during init")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        fail,
    )

    indicator = LLMOverrideIndicator()

    rendered = indicator._build_initial_content()
    assert isinstance(rendered, Text)
    assert rendered.plain == " ... "
    assert "cyan" in str(rendered.style)
    assert indicator._cached_default is None
    assert indicator._cached_default_failed is False


async def test_async_default_resolution_updates_cached_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The async resolver path populates the cached default once mounted."""

    monkeypatch.setattr(
        indicator_module,
        "build_launch_model_setting_snapshot",
        lambda *a, **k: _snapshot(provider="claude", model="sonnet"),
    )

    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#llm-override-indicator", LLMOverrideIndicator
        )
        await page.wait_for(lambda _state: indicator._cached_default is not None)
        cached = indicator._cached_default

    assert cached == ("claude", "sonnet")
    rendered = indicator._build_initial_content()
    assert isinstance(rendered, Text)
    assert rendered.plain == " CLAUDE(sonnet) "


async def test_click_opens_models_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async with AcePage() as page:
        monkeypatch.setattr(
            page.app,
            "_open_models_panel",
            lambda: calls.append("opened"),
        )
        indicator = page.query_one_widget(
            "#llm-override-indicator", LLMOverrideIndicator
        )
        await indicator.on_click()
        await page.pause()

    assert calls == ["opened"]


def test_refresh_does_not_rearm_when_token_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indicator, scheduled = _prepare_indicator(monkeypatch, token=("token-a",))
    indicator._cached_default = ("claude", "opus")
    indicator._cached_default_token = ("token-a",)

    indicator.refresh()

    assert scheduled == []


def test_refresh_rearms_when_token_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    indicator, scheduled = _prepare_indicator(monkeypatch, token=("token-b",))
    indicator._cached_default = ("claude", "opus")
    indicator._cached_default_token = ("token-a",)

    indicator.refresh()

    assert len(scheduled) == 1


def test_refresh_rearms_while_failed_flag_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indicator, scheduled = _prepare_indicator(monkeypatch, token=("token-a",))
    indicator._cached_default = ("claude", "opus")
    indicator._cached_default_token = ("token-a",)
    indicator._cached_default_failed = True

    indicator.refresh()

    assert len(scheduled) == 1


def test_refresh_rearms_when_override_lapses(monkeypatch: pytest.MonkeyPatch) -> None:
    indicator, scheduled = _prepare_indicator(
        monkeypatch, override=None, token=("token-a",)
    )
    indicator._cached_default = ("claude", "opus")
    indicator._cached_default_token = ("token-a",)
    indicator._override_active_last_tick = True

    indicator.refresh()

    assert len(scheduled) == 1


def test_refresh_keeps_stale_default_while_rearming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token-triggered re-arm must not flash the pill to a placeholder."""
    indicator, scheduled = _prepare_indicator(monkeypatch, token=("token-b",))
    indicator._cached_default = ("claude", "opus")
    indicator._cached_default_token = ("token-a",)

    indicator.refresh()

    assert scheduled
    assert indicator._cached_default == ("claude", "opus")
    assert indicator._build_cached_default_content().plain == " CLAUDE(opus) "


def test_refresh_never_calls_resolver_synchronously(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The resolver must only ever run inside the off-thread worker task."""

    def fail(*args: object, **kwargs: object) -> LaunchModelSettingSnapshot:
        raise AssertionError("resolver must not run on the UI thread")

    monkeypatch.setattr(indicator_module, "build_launch_model_setting_snapshot", fail)
    indicator, scheduled = _prepare_indicator(monkeypatch, token=("token-b",))
    indicator._cached_default_token = ("token-a",)

    indicator.refresh()

    assert len(scheduled) == 1


def test_worker_error_does_not_commit_token(monkeypatch: pytest.MonkeyPatch) -> None:
    indicator, _scheduled = _prepare_indicator(monkeypatch)
    indicator._pending_resolve_token = ("pending-token",)
    indicator._resolve_in_flight = True

    indicator.on_worker_state_changed(
        _FakeStateChanged(
            _FakeWorker(indicator_module._DEFAULT_WORKER_GROUP, None),
            WorkerState.ERROR,
        )
    )

    assert indicator._cached_default_token is None
    assert indicator._cached_default_failed is True
    assert indicator._resolve_in_flight is False


def test_worker_success_commits_pending_token(monkeypatch: pytest.MonkeyPatch) -> None:
    indicator, _scheduled = _prepare_indicator(monkeypatch)
    indicator._pending_resolve_token = ("pending-token",)
    indicator._resolve_in_flight = True
    snapshot = indicator_module._LaunchDefaultSnapshot(
        provider="claude",
        model="opus",
        referenced_alias=None,
        selector_mode=None,
        member_count=0,
    )

    indicator.on_worker_state_changed(
        _FakeStateChanged(
            _FakeWorker(indicator_module._DEFAULT_WORKER_GROUP, snapshot),
            WorkerState.SUCCESS,
        )
    )

    assert indicator._cached_default == ("claude", "opus")
    assert indicator._cached_default_token == ("pending-token",)
    assert indicator._resolve_in_flight is False
    assert indicator._cached_default_failed is False


def test_tooltip_adds_rotation_line_for_round_robin_pool() -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("claude", "opus")
    indicator._cached_snapshot = indicator_module._LaunchDefaultSnapshot(
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
        "No temporary override active.\n"
        "Press ,m for Launch Control."
    )


def test_tooltip_omits_rotation_line_for_non_pool_default() -> None:
    indicator = LLMOverrideIndicator()
    indicator._cached_default = ("claude", "opus")
    indicator._cached_snapshot = indicator_module._LaunchDefaultSnapshot(
        provider="claude",
        model="opus",
        referenced_alias=None,
        selector_mode=None,
        member_count=0,
    )

    tooltip = indicator._build_tooltip(None)

    assert tooltip == (
        "Launch default: CLAUDE(opus)\n"
        "No temporary override active.\n"
        "Press ,m for Launch Control."
    )
