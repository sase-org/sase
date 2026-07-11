"""Tests for :mod:`sase.ace.tui.modals.models_panel` and its leader dispatch.

Phase 2 (epic sase-5e): the Models panel replaces the single-purpose temporary
override modal. Covers row rendering, the duration picker, the per-alias
set/change/clear flows, and the renamed ``,m`` leader action (plus its
back-compat with the old ``temporary_llm_override`` action id).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, call

import pytest
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import OptionList, Static

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
from sase.ace.tui.modals.custom_model_input_modal import CustomModelInputModal
from sase.ace.tui.modals.model_picker_modal import CUSTOM_SENTINEL, ModelPickerModal
from sase.ace.tui.modals.models_panel import (
    ModelsPanel,
    ModelsPanelResult,
    _DurationPickerModal,
    _description_text_for_view,
    _format_duration_chosen,
    _format_remaining,
    _kind_label,
    _provider_model_column_width,
    _state_tag,
    _render_alias_row,
)
from sase.ace.tui.modals.models_panel_duration import (
    OPEN_OVERRIDE_UNTIL,
    OVERRIDE_UNTIL_CLEARED,
    RelativeOverrideDuration,
)
from sase.ace.tui.modals.models_panel_time import (
    OVERRIDE_UNTIL_BACK,
    OverrideUntilModal,
    ResolvedOverrideUntil,
)
from sase.ace.tui.modals.models_panel_rendering import (
    description_text_for_row,
    render_bucket_row,
)
from sase.ace.tui.widgets import AliasOverridesIndicator, LLMOverrideIndicator
from sase.llm_provider import AliasKind, AliasView, BucketView, TemporaryLLMOverride
from tests._temporary_llm_override_helpers import full_registry

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class _StyledTestApp(_TestApp):
    """Test app that loads the production ``styles.tcss`` so pushed modals lay
    out exactly as they do in the real TUI — required for asserting rendered
    geometry (as opposed to just widget content)."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"


def _view(
    name: str,
    kind: AliasKind,
    *,
    configured: bool = False,
    configured_value: str | None = None,
    provider: str | None = "claude",
    model: str = "opus",
    override: TemporaryLLMOverride | None = None,
    configured_source: str | None = None,
    description: str | None = None,
    bucket: str | None = None,
) -> AliasView:
    return AliasView(
        name=name,
        kind=kind,
        configured=configured,
        configured_value=configured_value,
        provider=provider,
        model=model,
        override=override,
        configured_source=configured_source,
        description=description,
        bucket=bucket,
    )


def _override(expires_at: float | None = 3600.0) -> TemporaryLLMOverride:
    return TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="codex/o3",
        created_at=0.0,
        expires_at=expires_at,
        source="test",
    )


# ---------------------------------------------------------------------------
# Duration / formatting helpers
# ---------------------------------------------------------------------------


def test_format_remaining_hours_minutes() -> None:
    assert _format_remaining(3600 + 30 * 60) == "1h30m"


def test_format_remaining_seconds_when_subminute() -> None:
    assert _format_remaining(45) == "45s"


def test_format_remaining_clamps_negative() -> None:
    assert _format_remaining(-10) == "0s"


def test_format_duration_chosen_until_cleared() -> None:
    assert _format_duration_chosen(None) == "until cleared"


def test_format_duration_chosen_finite() -> None:
    assert _format_duration_chosen(90 * 60.0) == "1h30m"


# ---------------------------------------------------------------------------
# Row rendering
# ---------------------------------------------------------------------------


def test_kind_label_provider_coder_shows_coder() -> None:
    view = _view("codex_coder", "provider_coder")
    assert _kind_label(view) == "coder"


def test_state_tag_configured() -> None:
    view = _view("myalias", "user", configured=True, configured_value="claude/opus")
    text, _ = _state_tag(view, now=0.0)
    assert text == "configured"


def test_state_tag_implicit_default() -> None:
    text, _ = _state_tag(_view("default", "default"), now=0.0)
    assert text == "implicit"


def test_state_tag_implicit_role() -> None:
    text, _ = _state_tag(_view("coder", "role"), now=0.0)
    assert text == "implicit → @default"


def test_state_tag_implicit_provider_coder() -> None:
    text, _ = _state_tag(_view("codex_coder", "provider_coder"), now=0.0)
    assert text == "implicit → @coder"


def test_state_tag_override_with_remaining() -> None:
    view = _view("coder", "role", override=_override(expires_at=3600.0))
    text, _ = _state_tag(view, now=0.0)
    assert text == "override · 1h left"


def test_state_tag_override_until_cleared() -> None:
    view = _view("coder", "role", override=_override(expires_at=None))
    text, _ = _state_tag(view, now=0.0)
    assert text == "override · until cleared"


def test_render_alias_row_contains_name_provider_and_state() -> None:
    view = _view("phase_worker", "role", provider="codex", model="o3")
    width = _provider_model_column_width([view])
    line = _render_alias_row(view, now=0.0, provider_model_width=width).plain
    assert "phase_worker" in line
    assert "CODEX(o3)" in line
    assert "implicit → @default" in line


def test_render_alias_rows_align_state_column() -> None:
    """Rows with different badge widths share one state-column start cell."""
    short = _view("codex_coder", "provider_coder", provider="codex", model="o3")
    wide = _view(
        "fast",
        "user",
        configured=True,
        configured_value="claude/haiku",
        provider="claude",
        model="haiku",
    )
    # The wider badge (CLAUDE(haiku)) drives the shared column width.
    width = _provider_model_column_width([short, wide])
    assert width == len("CLAUDE(haiku)")

    short_line = _render_alias_row(short, now=0.0, provider_model_width=width).plain
    wide_line = _render_alias_row(wide, now=0.0, provider_model_width=width).plain
    short_state, _ = _state_tag(short, now=0.0)
    wide_state, _ = _state_tag(wide, now=0.0)

    assert short_state in short_line
    assert wide_state in wide_line
    assert short_line.index(short_state) == wide_line.index(wide_state)


def test_render_alias_row_preserves_production_length_provider_model_label() -> None:
    """A representative badge that exceeded the old cap remains readable."""
    view = _view(
        "default",
        "default",
        provider="claude",
        model="claude-fable-4-10",
    )

    width = _provider_model_column_width([view])
    line = _render_alias_row(view, now=0.0, provider_model_width=width).plain

    assert width == len("CLAUDE(claude-fable-4-10)")
    assert "CLAUDE(claude-fable-4-10)" in line
    assert "…" not in line


def test_render_alias_row_ellipsizes_long_provider_model_label() -> None:
    """An over-cap badge is ellipsized but the state tag still aligns."""
    long_view = _view(
        "mega",
        "user",
        configured=True,
        configured_value="opencode/really-long",
        provider="opencode",
        model="anthropic/claude-sonnet-4-5-extremely-long-model-name",
    )
    short = _view("codex_coder", "provider_coder", provider="codex", model="o3")

    width = _provider_model_column_width([long_view, short])
    assert width == models_panel._PROVIDER_MODEL_CELL_MAX

    long_line = _render_alias_row(long_view, now=0.0, provider_model_width=width).plain
    short_line = _render_alias_row(short, now=0.0, provider_model_width=width).plain
    long_state, _ = _state_tag(long_view, now=0.0)
    short_state, _ = _state_tag(short, now=0.0)

    # The badge was truncated with an ellipsis, yet the state tag is present
    # and starts at the same cell as the short row's state tag.
    assert "…" in long_line
    assert long_state in long_line
    assert long_line.index(long_state) == short_line.index(short_state)


def test_description_text_for_builtin_alias() -> None:
    text = _description_text_for_view(
        _view(
            "default",
            "default",
            description="Model used when a prompt has no %model directive.",
        )
    )

    assert text.plain == "Model used when a prompt has no %model directive."


def test_description_text_for_custom_alias() -> None:
    text = _description_text_for_view(
        _view(
            "blogger",
            "user",
            configured=True,
            configured_source="custom",
            description="Draft and edit blog posts.",
        )
    )

    assert text.plain == "Draft and edit blog posts."


def test_description_text_for_user_alias_without_description_hints_config_path() -> (
    None
):
    text = _description_text_for_view(
        _view(
            "blogger",
            "user",
            configured=True,
            configured_source="builtin",
            description=None,
        )
    )

    assert "no description" in text.plain
    assert "llm_provider.model_aliases.custom.blogger.description" in text.plain


def test_render_bucket_row_contains_count_and_override_state() -> None:
    bucket = BucketView(
        name="research",
        description="Research roles.",
        members=(
            _view("research_a", "user", bucket="research", override=_override()),
            _view("research_b", "user", bucket="research"),
        ),
    )

    line = render_bucket_row(bucket, provider_model_width=13).plain

    assert "▸ bucket" in line
    assert "research" in line
    assert "2 aliases" in line
    assert "override · 1 active" in line


def test_description_text_for_bucket_shows_description_and_model_mix() -> None:
    bucket = BucketView(
        name="research",
        description="Research roles.",
        members=(
            _view(
                "research_a",
                "user",
                provider="codex",
                model="gpt-5.6-sol",
                bucket="research",
            ),
            _view(
                "research_b",
                "user",
                provider="claude",
                model="opus",
                bucket="research",
            ),
            _view(
                "research_c",
                "user",
                provider="codex",
                model="gpt-5.6-sol",
                bucket="research",
            ),
        ),
    )

    text = description_text_for_row(bucket).plain

    assert text.splitlines() == [
        "Research roles.",
        "codex/gpt-5.6-sol ×2 · claude/opus ×1",
    ]


# ---------------------------------------------------------------------------
# Duration picker presets
# ---------------------------------------------------------------------------


def _make_duration_modal() -> _DurationPickerModal:
    modal = _DurationPickerModal()
    modal.dismiss = MagicMock()  # type: ignore[method-assign,assignment]
    return modal


def test_duration_preset_1_returns_15m() -> None:
    modal = _make_duration_modal()
    modal.action_preset_1()
    modal.dismiss.assert_called_once_with(RelativeOverrideDuration(15 * 60.0))


def test_duration_preset_3_returns_1h() -> None:
    modal = _make_duration_modal()
    modal.action_preset_3()
    modal.dismiss.assert_called_once_with(RelativeOverrideDuration(60 * 60.0))


def test_duration_preset_6_until_cleared_returns_none() -> None:
    modal = _make_duration_modal()
    modal.action_preset_6()
    modal.dismiss.assert_called_once_with(OVERRIDE_UNTIL_CLEARED)


def test_duration_t_opens_specific_time_path() -> None:
    modal = _make_duration_modal()
    modal.action_choose("t")
    modal.dismiss.assert_called_once_with(OPEN_OVERRIDE_UNTIL)


# ---------------------------------------------------------------------------
# Panel actions — no-mount unit coverage
# ---------------------------------------------------------------------------


def test_action_close_dismisses_unchanged() -> None:
    panel = ModelsPanel()
    panel.dismiss = MagicMock()  # type: ignore[method-assign,assignment]
    panel.action_close()
    (arg,), _ = panel.dismiss.call_args
    assert isinstance(arg, ModelsPanelResult)
    assert arg.changed is False


def test_on_duration_picked_cancel_is_noop(monkeypatch) -> None:
    panel = ModelsPanel()
    panel._refresh_rows = MagicMock()  # type: ignore[method-assign]
    set_mock = MagicMock()
    monkeypatch.setattr(models_panel, "set_alias_override", set_mock)
    panel._on_duration_picked(models_panel.DURATION_CHOICE_CANCELLED)
    set_mock.assert_not_called()
    assert panel._changed is False


async def test_on_duration_picked_invalid_notifies_error(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])
    monkeypatch.setattr(
        models_panel,
        "set_alias_override",
        MagicMock(side_effect=ValueError("nope")),
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._pending_raw_model = "bad"
        panel._on_duration_picked(RelativeOverrideDuration(60.0))
        await pilot.pause()
        await pilot.pause()
        assert panel._changed is False
        panel.notify.assert_called_once()
        assert panel.notify.call_args.kwargs.get("severity") == "error"


# ---------------------------------------------------------------------------
# Panel interaction — pilot flows
# ---------------------------------------------------------------------------


def _patch_views(
    monkeypatch,
    views: list[AliasView],
    *,
    bucket_descriptions: dict[str, str] | None = None,
) -> None:
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: views)
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.model_alias_bucket_description",
        lambda name: (bucket_descriptions or {}).get(name),
    )
    monkeypatch.setattr(models_panel, "_now", lambda: 0.0)


def _bucketed_views() -> list[AliasView]:
    return [
        _view(
            "research_a",
            "user",
            configured=True,
            configured_source="custom",
            provider="codex",
            model="gpt-5.6-sol",
            description="Lead researcher.",
            bucket="research",
        ),
        _view(
            "research_b",
            "user",
            configured=True,
            configured_source="custom",
            provider="claude",
            model="opus",
            description="Second-opinion researcher.",
            bucket="research",
        ),
        _view(
            "plain",
            "user",
            configured=True,
            configured_source="custom",
            description="Ungrouped alias.",
        ),
    ]


async def test_panel_escape_closes_unchanged(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("default", "default")])
    result: ModelsPanelResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: ModelsPanelResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(ModelsPanel(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert isinstance(result, ModelsPanelResult)
    assert result.changed is False


async def test_panel_o_opens_model_picker(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(ModelsPanel())
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelPickerModal)


async def test_panel_x_clears_active_override(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("phase_worker", "role", override=_override())])
    clear_mock = MagicMock(return_value=True)
    monkeypatch.setattr(models_panel, "clear_alias_override", clear_mock)
    result: ModelsPanelResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: ModelsPanelResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(ModelsPanel(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    clear_mock.assert_called_once_with("phase_worker")
    assert isinstance(result, ModelsPanelResult)
    assert result.changed is True


async def test_panel_x_without_override_does_not_clear(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("coder", "role", override=None)])
    clear_mock = MagicMock()
    monkeypatch.setattr(models_panel, "clear_alias_override", clear_mock)

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        clear_mock.assert_not_called()
        assert panel._changed is False


async def test_panel_description_strip_updates_on_highlight(monkeypatch) -> None:
    _patch_views(
        monkeypatch,
        [
            _view("default", "default", description="Default model."),
            _view(
                "blogger",
                "user",
                configured=True,
                configured_source="custom",
                description="Draft blog posts.",
            ),
        ],
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        description = panel.query_one("#models-panel-description", Static)
        assert "Default model." in description.content.plain
        await pilot.press("j")
        await pilot.pause()
        assert "Draft blog posts." in description.content.plain


async def test_panel_l_drills_into_bucket_and_h_restores_bucket(monkeypatch) -> None:
    _patch_views(
        monkeypatch,
        _bucketed_views(),
        bucket_descriptions={"research": "Research roles."},
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        assert panel._highlighted_row_id() == "bucket:research"
        assert "l/enter" in str(panel.query_one("#models-panel-footer", Static).content)
        assert (
            "Research roles."
            in panel.query_one("#models-panel-description", Static).content.plain
        )

        await pilot.press("l")
        await pilot.pause()
        assert panel._active_bucket == "research"
        assert panel._highlighted_row_id() == "research_a"
        assert panel.query_one("#models-panel-title", Static).content.plain == (
            "Models › research"
        )
        assert "h" in str(panel.query_one("#models-panel-footer", Static).content)

        await pilot.press("h")
        await pilot.pause()
        assert panel._active_bucket is None
        assert panel._highlighted_row_id() == "bucket:research"
        assert panel.query_one("#models-panel-title", Static).content.plain == "Models"


async def test_panel_enter_drills_into_bucket(monkeypatch) -> None:
    _patch_views(monkeypatch, _bucketed_views())

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert panel._active_bucket == "research"
        assert panel._highlighted_row_id() == "research_a"


@pytest.mark.parametrize("key", ["o", "x", "e", "r"])
async def test_alias_actions_on_bucket_are_guarded(monkeypatch, key: str) -> None:
    _patch_views(monkeypatch, _bucketed_views())

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()

        assert pilot.app.screen is panel
        panel.notify.assert_called_once_with("Press `l`/`enter` to open this bucket")


async def test_refresh_auto_leaves_bucket_when_last_member_disappears(
    monkeypatch,
) -> None:
    views = [_bucketed_views()[0]]
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: views)
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.model_alias_bucket_description",
        lambda name: None,
    )
    monkeypatch.setattr(models_panel, "_now", lambda: 0.0)

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        assert panel._active_bucket == "research"

        views.clear()
        panel._refresh_rows(keep="research_a")
        await pilot.pause()

        assert panel._active_bucket is None
        assert panel.query_one("#models-panel-title", Static).content.plain == "Models"
        assert panel.query_one("#models-panel-list", OptionList).option_count == 0


async def test_panel_preferred_width_fits_production_description(monkeypatch) -> None:
    """The strip must lay out with a non-zero content area, not just hold text.

    Regression for the invisible-strip bug: the Static's ``content`` was always
    set correctly, but a border-box ``height: 2`` (1 border-top + 1 padding-top)
    left 0 rows for content, so the description text rendered fully clipped.
    Asserting ``content_size.height`` catches "content set but not visible".

    Uses ``_StyledTestApp`` (loads the real ``styles.tcss``) because the bug and
    its fix live entirely in that stylesheet; the default ``_TestApp`` applies
    no CSS and so cannot exercise the border-box height math.
    """
    description_text = (
        "Model used when a prompt has no %model directive; every other alias "
        "ultimately falls back to it."
    )
    assert len(description_text) == 96
    _patch_views(
        monkeypatch,
        [_view("default", "default", description=description_text)],
    )

    async with _StyledTestApp().run_test(size=(120, 40)) as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        container = panel.query_one("#models-panel-container", Container)
        description = panel.query_one("#models-panel-description", Static)
        assert container.region.width == 110
        assert description.content.plain == description_text
        assert description.content_size.width >= len(description_text)
        assert description.content_size.height == 2


async def test_panel_width_is_contained_by_narrow_viewport(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("default", "default")])

    async with _StyledTestApp().run_test(size=(80, 40)) as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        container = panel.query_one("#models-panel-container", Container)

        assert container.region.x >= 0
        assert container.region.right <= panel.size.width


async def test_set_flow_threads_model_and_duration(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])
    fake = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="o3",
        created_at=0.0,
        expires_at=3600.0,
        source="ace",
    )
    set_mock = MagicMock(return_value=fake)
    monkeypatch.setattr(models_panel, "set_alias_override", set_mock)

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._on_model_picked("o3")
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)
        panel._on_duration_picked(RelativeOverrideDuration(3600.0))
        await pilot.pause()

    set_mock.assert_called_once_with("coder", "o3", 3600.0, source="ace")
    assert panel._changed is True


async def test_t_opens_until_modal_and_back_reopens_duration(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._pending_raw_model = "o3"
        panel._on_duration_picked(OPEN_OVERRIDE_UNTIL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, OverrideUntilModal)
        panel._on_override_until_picked(OVERRIDE_UNTIL_BACK)
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)


async def test_exact_time_flow_dispatches_exact_api(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])
    fake = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="o3",
        created_at=1000.0,
        expires_at=2000.0,
        source="ace",
    )
    exact_set = MagicMock(return_value=fake)
    relative_set = MagicMock()
    monkeypatch.setattr(models_panel, "set_alias_override_until", exact_set)
    monkeypatch.setattr(models_panel, "set_alias_override", relative_set)
    resolved = ResolvedOverrideUntil(
        target=datetime.fromtimestamp(2000, UTC),
        expires_at=2000.0,
        target_display="Ends Thu Jan 1 at 12:33 AM EST",
        notification_display="Thu Jan 1, 12:33 AM EST",
        remaining_display="16m",
        timezone_display="America/New_York",
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._pending_raw_model = "o3"
        panel._on_override_until_picked(resolved)
        await pilot.pause()
        await pilot.pause()

    exact_set.assert_called_once_with("coder", "o3", 2000.0, source="ace")
    relative_set.assert_not_called()
    assert panel._changed is True


async def test_custom_model_path_opens_input_then_duration(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._on_model_picked(CUSTOM_SENTINEL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, CustomModelInputModal)
        panel._on_custom_picked("codex/o3")
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)
        assert panel._pending_raw_model == "codex/o3"


# ---------------------------------------------------------------------------
# Leader-mode dispatch
# ---------------------------------------------------------------------------


def test_leader_handler_dispatches_models_panel() -> None:
    mixin = MagicMock()
    mixin._keymap_registry = full_registry()
    mixin.current_tab = "changespecs"
    mixin.marked_indices = []
    mixin._leader_mode_active = True

    handled = LeaderModeMixin._handle_leader_key(cast(LeaderModeMixin, mixin), "m")

    assert handled is True
    mixin._open_models_panel.assert_called_once()


def test_leader_handler_honors_legacy_action_id() -> None:
    """A user keymap still binding the old action id keeps opening the panel."""
    mixin = MagicMock()
    mixin._keymap_registry = full_registry(
        {
            "keymaps": {
                "modes": {"leader_mode": {"keys": {"temporary_llm_override": "z"}}}
            }
        }
    )
    mixin.current_tab = "changespecs"
    mixin.marked_indices = []
    mixin._leader_mode_active = True

    handled = LeaderModeMixin._handle_leader_key(cast(LeaderModeMixin, mixin), "z")

    assert handled is True
    mixin._open_models_panel.assert_called_once()


def test_open_models_panel_refreshes_indicators_when_changed() -> None:
    mixin = MagicMock()
    default_indicator = MagicMock(spec=LLMOverrideIndicator)
    alias_indicator = MagicMock(spec=AliasOverridesIndicator)
    indicators = {
        "#llm-override-indicator": default_indicator,
        "#alias-overrides-indicator": alias_indicator,
    }
    mixin.query_one.side_effect = lambda selector, _type: indicators[selector]

    LeaderModeMixin._open_models_panel(cast(LeaderModeMixin, mixin))

    callback = mixin.push_screen.call_args.kwargs["callback"]
    callback(ModelsPanelResult(changed=True))

    assert mixin.query_one.call_args_list == [
        call("#llm-override-indicator", LLMOverrideIndicator),
        call("#alias-overrides-indicator", AliasOverridesIndicator),
    ]
    default_indicator.refresh.assert_called_once()
    alias_indicator.refresh.assert_called_once()


def test_open_models_panel_no_refresh_when_unchanged() -> None:
    mixin = MagicMock()

    LeaderModeMixin._open_models_panel(cast(LeaderModeMixin, mixin))

    callback = mixin.push_screen.call_args.kwargs["callback"]
    callback(ModelsPanelResult(changed=False))

    mixin.query_one.assert_not_called()
