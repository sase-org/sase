"""Tests for model picker option and row construction."""

from rich.text import Text

from sase.ace.tui.modals.model_picker_modal import CUSTOM_SENTINEL, DEFAULT_SENTINEL
from sase.ace.tui.modals.model_picker_options import (
    build_model_options,
    rows_to_options,
)
from sase.ace.tui.modals.model_picker_rows import ModelPickerRow, build_model_rows
from sase.ace.tui.provider_styles import _provider_style_for


def test_build_model_options_has_default() -> None:
    """The option list should start with 'Follow-up default'."""
    options = build_model_options()
    assert options[0] is not None
    assert options[0].id == "__default__"
    assert str(options[0].prompt) == "Follow-up default"


def test_build_model_options_has_custom() -> None:
    """The option list should end with 'Custom...'."""
    options = build_model_options()
    # Last non-None item
    non_none = [o for o in options if o is not None]
    assert non_none[-1].id == CUSTOM_SENTINEL


def test_build_model_options_has_known_models() -> None:
    """The option list should include known models from registry."""
    options = build_model_options()
    ids = {o.id for o in options if o is not None}
    assert "opus" in ids
    assert "sonnet" in ids
    assert "claude-haiku-4-5" in ids
    assert "claude-fable-5" in ids
    assert "o3" in ids
    assert "gpt-5.6-sol" in ids
    assert "gpt-5.5" in ids
    assert "gpt-5.3-codex-spark" in ids
    assert "gemini-3.6-flash-high" in ids


def test_build_model_options_has_separators() -> None:
    """The option list should include None separators."""
    options = build_model_options()
    assert None in options


def test_provider_style_uses_plugin_primary_with_builtin_accents() -> None:
    """Provider palettes should be deterministic and provider-specific."""
    codex = _provider_style_for("codex")
    claude = _provider_style_for("claude")
    assert codex.name_style == "bold #10A37F"
    assert codex.model_style == "#63D9B6"
    assert claude.name_style == "bold #D97757"
    assert claude.model_style == "#FFAF00"
    assert _provider_style_for("mystery").name_style == "bold #AF87D7"


def test_model_picker_provider_headers_include_count_and_style() -> None:
    """Provider header rows should render as styled Rich text with counts."""
    rows = build_model_rows()
    options = [option for option in rows_to_options(rows) if option is not None]
    claude_header = next(
        option for option in options if option.id == "__header_claude__"
    )

    assert isinstance(claude_header.prompt, Text)
    assert "CLAUDE" in claude_header.prompt.plain
    assert "models" in claude_header.prompt.plain
    assert any(span.style == "bold #D97757" for span in claude_header.prompt.spans)


def test_model_picker_model_rows_include_alias_as_dim_secondary_text() -> None:
    """Model rows should keep ids primary and aliases visually secondary."""
    row = ModelPickerRow(
        kind="model",
        label="    anthropic/claude-sonnet-4-5  (sonnet45)",
        option_id="anthropic/claude-sonnet-4-5",
        provider="opencode",
        model_id="anthropic/claude-sonnet-4-5",
        alias="sonnet45",
    )
    option = rows_to_options([row])[0]

    assert option is not None
    assert isinstance(option.prompt, Text)
    assert option.prompt.plain.startswith("   anthropic/claude-sonnet-4-5")
    assert "sonnet45" in option.prompt.plain
    assert any(span.style == "dim #E6D18A" for span in option.prompt.spans)


def test_model_picker_claude_fable_row_includes_alias() -> None:
    """Claude Fable 5 should appear in the claude group with its short alias."""
    rows = build_model_rows()
    row = next(row for row in rows if row.option_id == "claude-fable-5")
    option = rows_to_options([row])[0]

    assert row.provider == "claude"
    assert row.model_id == "claude-fable-5"
    assert row.alias == "fable"
    assert row.label == "    claude-fable-5  (fable)"
    assert option is not None
    assert isinstance(option.prompt, Text)
    assert "claude-fable-5" in option.prompt.plain
    assert "fable" in option.prompt.plain
    assert any(span.style == "dim #D7AF87" for span in option.prompt.spans)


def test_model_picker_codex_spark_row_includes_alias() -> None:
    """Codex Spark should be in the codex group with its short alias."""
    rows = build_model_rows()
    row = next(row for row in rows if row.option_id == "gpt-5.3-codex-spark")
    option = rows_to_options([row])[0]

    assert row.provider == "codex"
    assert row.model_id == "gpt-5.3-codex-spark"
    assert row.alias == "gpt53spark"
    assert row.label == "    gpt-5.3-codex-spark  (gpt53spark)"
    assert option is not None
    assert isinstance(option.prompt, Text)
    assert "gpt-5.3-codex-spark" in option.prompt.plain
    assert "gpt53spark" in option.prompt.plain


def test_model_picker_claude_point_version_rows_are_absent() -> None:
    """Point-version Opus/Sonnet rows should not be in picker options."""
    rows = build_model_rows()
    row_ids = {row.option_id for row in rows}
    assert "claude-opus-5" not in row_ids
    assert "claude-sonnet-5" not in row_ids


def test_model_picker_hides_fakey_provider_group_and_models() -> None:
    """The fakey test provider must never appear in the modal model picker."""
    rows = build_model_rows()
    options = [option for option in rows_to_options(rows) if option is not None]
    row_ids = {row.option_id for row in rows}

    assert "__header_fakey__" not in row_ids
    assert not any(option.id == "__header_fakey__" for option in options)
    assert "fakey-large" not in row_ids
    assert "fakey-small" not in row_ids
    # Every other provider group remains present, and the escape hatches stay.
    assert "__header_claude__" in row_ids
    assert "__header_codex__" in row_ids
    assert DEFAULT_SENTINEL in row_ids
    assert CUSTOM_SENTINEL in row_ids


def test_model_picker_claude_h4_5_row_includes_alias() -> None:
    """Remaining explicit Claude point-model should be pickable with its short alias."""
    rows = build_model_rows()
    expected = {"claude-haiku-4-5": "haiku45"}

    for model_id, alias in expected.items():
        row = next(row for row in rows if row.option_id == model_id)
        assert row.provider == "claude"
        assert row.model_id == model_id
        assert row.alias == alias
        assert row.label == f"    {model_id}  ({alias})"
