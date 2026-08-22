"""Models panel alias row and section rendering tests."""

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.modals.models_panel import (
    _provider_model_column_width,
    _render_alias_row,
    _state_tag,
)
from sase.ace.tui.modals.models_panel_rendering import (
    _section_count_label,
    custom_builtin_shadow_warning_message,
    panel_value_column_width,
    render_empty_custom_hint,
    render_launch_settings_header,
    render_panel_row,
    render_section_header,
)
from sase.ace.tui.modals.models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    DefaultEffortSettingRow,
    LaunchModelSettingRow,
    RunnerLimitSettingRow,
)
from sase.config import DEFAULT_MAX_RUNNING_AGENTS, EffectiveRunnerLimitSnapshot
from sase.llm_provider import EffectiveDefaultEffortSnapshot, ModelsPanelSection
from sase.llm_provider.config import LaunchModelSettingSnapshot
from tests._models_panel_helpers import make_alias_view


def test_custom_builtin_warning_message_uses_singular_guidance() -> None:
    assert custom_builtin_shadow_warning_message(["small"]) == (
        "Builtin alias @small is configured under "
        "llm_provider.model_aliases.custom. Move its model value from "
        "llm_provider.model_aliases.custom to llm_provider.model_aliases.builtin."
    )


def test_render_alias_row_contains_name_provider_and_state() -> None:
    view = make_alias_view("medium", "role", provider="codex", model="o3")
    width = _provider_model_column_width([view])
    line = _render_alias_row(view, now=0.0, provider_model_width=width).plain
    assert "medium" in line
    assert "CODEX(o3)" in line
    assert "implicit" in line


def test_render_alias_row_ownership_gutter_is_semantic() -> None:
    builtin = make_alias_view(
        "small",
        "role",
        configured=True,
        configured_source="custom",
    )
    user = make_alias_view(
        "researcher",
        "user",
        configured=True,
        configured_source="builtin",
    )

    builtin_line = _render_alias_row(builtin, now=0.0, provider_model_width=12).plain
    user_line = _render_alias_row(user, now=0.0, provider_model_width=12).plain

    assert builtin_line.startswith("  ! small")
    assert not builtin_line.startswith("▌")
    assert user_line.startswith("▌ researcher")


def test_render_section_header_aligns_counts_with_row_state_column() -> None:
    view = make_alias_view(
        "researcher",
        "user",
        configured=True,
        provider="codex",
        model="gpt-5.6-sol",
    )
    width = _provider_model_column_width([view])
    section = ModelsPanelSection("user", (view,), alias_count=1, bucket_count=0)

    header = render_section_header(section, provider_model_width=width).plain
    row = _render_alias_row(view, now=0.0, provider_model_width=width).plain

    assert header.startswith("▌ ── Your aliases ")
    assert header.index("1 alias") == row.index("configured")


def test_render_launch_setting_row_shows_raw_and_effective_model() -> None:
    row = LaunchModelSettingRow(
        field="default_model",
        label="default model",
        detail="Used when a launch has no explicit %model directive.",
        snapshot=LaunchModelSettingSnapshot(
            field="default_model",
            config_path="llm_provider.default_model",
            raw_value="@large",
            provider="claude",
            model="opus",
            effort="xhigh",
            provenance="shipped",
            referenced_alias="large",
            override_key="setting:default_model",
        ),
    )
    width = panel_value_column_width([row], now=0.0)

    header = render_launch_settings_header(value_width=width, count=1).plain
    line = render_panel_row(row, now=0.0, value_width=width).plain

    assert header.startswith("  ── Launch settings ")
    assert "1 setting" in header
    assert "default model" in line
    assert "@large → CLAUDE(opus) @ xhigh" in line
    assert "shipped" in line


def test_render_scalar_setting_rows_show_effective_values() -> None:
    effort_row = DefaultEffortSettingRow(
        EffectiveDefaultEffortSnapshot(
            configured_effort=None,
            temporary_override=None,
            captured_at=0.0,
        )
    )
    runner_row = RunnerLimitSettingRow(
        EffectiveRunnerLimitSnapshot(
            configured_limit=DEFAULT_MAX_RUNNING_AGENTS,
            temporary_override=None,
            captured_at=0.0,
        )
    )
    threshold_row = BigEpicPhaseThresholdSettingRow(1)
    width = panel_value_column_width([effort_row, runner_row, threshold_row], now=0.0)

    effort_line = render_panel_row(effort_row, now=0.0, value_width=width).plain
    runner_line = render_panel_row(runner_row, now=0.0, value_width=width).plain
    threshold_line = render_panel_row(threshold_row, now=0.0, value_width=width).plain

    assert "default effort" in effort_line
    assert "provider default" in effort_line
    assert "max runners" in runner_line
    assert str(DEFAULT_MAX_RUNNING_AGENTS) in runner_line
    assert "big epic starts at" in threshold_line
    assert "1 phase" in threshold_line


def test_render_rows_do_not_include_old_kind_column_labels() -> None:
    alias = make_alias_view("medium", "role", provider="codex", model="o3")
    setting = BigEpicPhaseThresholdSettingRow(5)
    alias_line = _render_alias_row(alias, now=0.0, provider_model_width=12).plain
    setting_line = render_panel_row(setting, now=0.0, value_width=12).plain

    assert not alias_line.startswith("  role")
    assert alias_line.startswith("  medium")
    assert " setting " not in setting_line
    assert "5 phases" in setting_line


def test_section_count_label_singularizes_and_omits_zero_buckets() -> None:
    one = ModelsPanelSection("builtin", (), alias_count=1, bucket_count=0)
    many = ModelsPanelSection("user", (), alias_count=3, bucket_count=1)

    assert _section_count_label(one) == "1 alias"
    assert _section_count_label(many) == "3 aliases · 1 bucket"


def test_empty_custom_hint_names_custom_config_path() -> None:
    hint = render_empty_custom_hint().plain

    assert hint.startswith("  No custom aliases")
    assert "llm_provider.model_aliases.custom" in hint


def test_render_alias_row_includes_effort_in_measured_badge() -> None:
    view = make_alias_view(
        "focused",
        "user",
        configured=True,
        provider="codex",
        model="o3",
        effort="max",
    )

    width = _provider_model_column_width([view])
    line = _render_alias_row(view, now=0.0, provider_model_width=width).plain

    assert width == len("CODEX(o3) @ max")
    assert "CODEX(o3) @ max" in line


def test_render_alias_rows_align_state_column() -> None:
    """Rows with different badge widths share one state-column start cell."""
    short = make_alias_view(
        "medium",
        "role",
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
        "large",
        "role",
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
        "quick",
        "user",
        configured=True,
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


def test_render_alias_row_ellipsizes_combined_badge_and_effort() -> None:
    view = make_alias_view(
        "focused",
        "user",
        configured=True,
        provider="claude",
        model="claude-fable-4-10-extra-long-context-model-name",
        effort="minimal",
    )

    width = _provider_model_column_width([view])
    line = _render_alias_row(view, now=0.0, provider_model_width=width).plain

    assert width == models_panel._PROVIDER_MODEL_CELL_MAX
    assert "…" in line
    assert "configured" in line
