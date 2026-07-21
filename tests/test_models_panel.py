"""Models panel rendering and duration-picker tests."""

from unittest.mock import MagicMock

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.modals.models_panel import (
    _DurationPickerModal,
    _description_text_for_view,
    _format_duration_chosen,
    _format_remaining,
    _kind_label,
    _provider_model_column_width,
    _render_alias_row,
    _state_tag,
)
from sase.ace.tui.modals.models_panel_duration import (
    OPEN_OVERRIDE_UNTIL,
    OVERRIDE_UNTIL_CLEARED,
    RelativeOverrideDuration,
)
from sase.ace.tui.modals.models_panel_rendering import (
    custom_builtin_shadow_warning_message,
    description_text_for_row,
    render_bucket_row,
)
from sase.llm_provider import BucketView
from tests._models_panel_helpers import make_alias_view, make_override


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


def test_custom_builtin_warning_message_uses_singular_guidance() -> None:
    assert custom_builtin_shadow_warning_message(["coder"]) == (
        "Builtin alias @coder is configured under "
        "llm_provider.model_aliases.custom. Move its model value from "
        "llm_provider.model_aliases.custom to llm_provider.model_aliases.builtin."
    )


def test_kind_label_provider_coder_shows_coder() -> None:
    view = make_alias_view("codex_coder", "provider_coder")
    assert _kind_label(view) == "coder"


def test_state_tag_configured() -> None:
    view = make_alias_view(
        "myalias",
        "user",
        configured=True,
        configured_value="claude/opus",
    )
    text = _state_tag(view, now=0.0)
    assert text.plain == "configured"


def test_state_tag_configured_reference_uses_shared_reference_accent() -> None:
    configured = _state_tag(
        make_alias_view(
            "coder",
            "role",
            configured=True,
            configured_value="@default",
        ),
        now=0.0,
    )
    implicit = _state_tag(
        make_alias_view("codex_coder", "provider_coder"),
        now=0.0,
    )

    assert configured.plain == "configured → @default"
    configured_target = next(
        span
        for span in configured.spans
        if configured.plain[span.start : span.end] == "@default"
    )
    implicit_target = next(
        span
        for span in implicit.spans
        if implicit.plain[span.start : span.end] == "@coder"
    )
    assert configured_target.style == implicit_target.style
    assert "#87d7ff" in str(configured_target.style).lower()


def test_state_tag_implicit_default() -> None:
    text = _state_tag(make_alias_view("default", "default"), now=0.0)
    assert text.plain == "implicit"


def test_state_tag_implicit_role() -> None:
    text = _state_tag(make_alias_view("coder", "role"), now=0.0)
    assert text.plain == "implicit → @default"


def test_state_tag_implicit_big_epic_lander() -> None:
    text = _state_tag(make_alias_view("big_epic_lander", "role"), now=0.0)
    assert text.plain == "implicit → @epic_lander"


def test_state_tag_implicit_size_phase_worker() -> None:
    text = _state_tag(make_alias_view("medium_phase_worker", "role"), now=0.0)
    assert text.plain == "implicit → @default"


def test_state_tag_implicit_provider_coder() -> None:
    text = _state_tag(
        make_alias_view("codex_coder", "provider_coder"),
        now=0.0,
    )
    assert text.plain == "implicit → @coder"


def test_custom_builtin_warning_survives_active_override() -> None:
    view = make_alias_view(
        "coder",
        "role",
        configured=True,
        configured_value="@default",
        configured_source="custom",
    )
    overridden = make_alias_view(
        "coder",
        "role",
        configured=True,
        configured_value="@default",
        configured_source="custom",
        override=make_override(),
    )

    line = _render_alias_row(view, now=0.0, provider_model_width=12).plain
    override_line = _render_alias_row(
        overridden, now=0.0, provider_model_width=12
    ).plain
    description = _description_text_for_view(view).plain

    assert line.startswith("! role")
    assert "configured → @default" in line
    assert override_line.startswith("! role")
    assert "override · 1h left" in override_line
    assert description.splitlines() == [
        "! Misplaced builtin alias: @coder",
        "Move its model value from llm_provider.model_aliases.custom to "
        "llm_provider.model_aliases.builtin.",
    ]


def test_state_tag_override_with_remaining() -> None:
    view = make_alias_view("coder", "role", override=make_override(expires_at=3600.0))
    text = _state_tag(view, now=0.0)
    assert text.plain == "override · 1h left"


def test_state_tag_override_until_cleared() -> None:
    view = make_alias_view("coder", "role", override=make_override(expires_at=None))
    text = _state_tag(view, now=0.0)
    assert text.plain == "override · until cleared"


def test_render_alias_row_contains_name_provider_and_state() -> None:
    view = make_alias_view("medium_phase_worker", "role", provider="codex", model="o3")
    width = _provider_model_column_width([view])
    line = _render_alias_row(view, now=0.0, provider_model_width=width).plain
    assert "medium_phase_worker" in line
    assert "CODEX(o3)" in line
    assert "implicit → @default" in line


def test_render_alias_rows_align_state_column() -> None:
    """Rows with different badge widths share one state-column start cell."""
    short = make_alias_view(
        "codex_coder",
        "provider_coder",
        provider="codex",
        model="o3",
    )
    wide = make_alias_view(
        "fast",
        "user",
        configured=True,
        configured_value="claude/haiku",
        provider="claude",
        model="haiku",
    )
    width = _provider_model_column_width([short, wide])
    assert width == len("CLAUDE(haiku)")

    short_line = _render_alias_row(short, now=0.0, provider_model_width=width).plain
    wide_line = _render_alias_row(wide, now=0.0, provider_model_width=width).plain
    short_state = _state_tag(short, now=0.0).plain
    wide_state = _state_tag(wide, now=0.0).plain

    assert short_state in short_line
    assert wide_state in wide_line
    assert short_line.index(short_state) == wide_line.index(wide_state)


def test_render_alias_row_preserves_production_length_provider_model_label() -> None:
    """A representative badge that exceeded the old cap remains readable."""
    view = make_alias_view(
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
    long_view = make_alias_view(
        "mega",
        "user",
        configured=True,
        configured_value="opencode/really-long",
        provider="opencode",
        model="anthropic/claude-sonnet-4-5-extremely-long-model-name",
    )
    short = make_alias_view(
        "codex_coder",
        "provider_coder",
        provider="codex",
        model="o3",
    )

    width = _provider_model_column_width([long_view, short])
    assert width == models_panel._PROVIDER_MODEL_CELL_MAX

    long_line = _render_alias_row(long_view, now=0.0, provider_model_width=width).plain
    short_line = _render_alias_row(short, now=0.0, provider_model_width=width).plain
    long_state = _state_tag(long_view, now=0.0).plain
    short_state = _state_tag(short, now=0.0).plain

    assert "…" in long_line
    assert long_state in long_line
    assert long_line.index(long_state) == short_line.index(short_state)


def test_description_text_for_builtin_alias() -> None:
    text = _description_text_for_view(
        make_alias_view(
            "default",
            "default",
            description="Model used when a prompt has no %model directive.",
        )
    )

    assert text.plain == "Model used when a prompt has no %model directive."


def test_description_text_for_custom_alias() -> None:
    text = _description_text_for_view(
        make_alias_view(
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
        make_alias_view(
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
            make_alias_view(
                "research_a",
                "user",
                bucket="research",
                override=make_override(),
            ),
            make_alias_view("research_b", "user", bucket="research"),
        ),
    )

    line = render_bucket_row(bucket, provider_model_width=13).plain

    assert "▸ bucket" in line
    assert "research" in line
    assert "2 aliases" in line
    assert "override · 1 active" in line


def test_render_bucket_row_and_description_surface_custom_builtin_warnings() -> None:
    bucket = BucketView(
        name="coders",
        description="Coder roles.",
        members=(
            make_alias_view(
                "coder",
                "role",
                configured=True,
                configured_source="custom",
                override=make_override(),
            ),
            make_alias_view("codex_coder", "provider_coder"),
        ),
    )

    line = render_bucket_row(bucket, provider_model_width=13).plain
    description = description_text_for_row(bucket).plain

    assert "▸ ! bucket" in line
    assert "! 1 misplaced" in line
    assert "1 override" in line
    assert description.splitlines() == [
        "! Misplaced builtin alias: @coder",
        "Move its model value from llm_provider.model_aliases.custom to "
        "llm_provider.model_aliases.builtin.",
    ]


def test_description_text_for_bucket_shows_description_and_model_mix() -> None:
    bucket = BucketView(
        name="research",
        description="Research roles.",
        members=(
            make_alias_view(
                "research_a",
                "user",
                provider="codex",
                model="gpt-5.6-sol",
                bucket="research",
            ),
            make_alias_view(
                "research_b",
                "user",
                provider="claude",
                model="opus",
                bucket="research",
            ),
            make_alias_view(
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
