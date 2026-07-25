"""Tests for model picker option and row construction."""

from rich.text import Text

from sase.ace.tui.modals.model_picker_modal import CUSTOM_SENTINEL
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
    assert "claude-opus-5" in ids
    assert "claude-sonnet-5" in ids
    assert "claude-haiku-4-5" in ids
    assert "claude-fable-5" in ids
    assert "o3" in ids
    assert "gpt-5.6-sol" in ids
    assert "gpt-5.5" in ids
    assert "Gemini 3.5 Flash (High)" in ids


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


def test_model_picker_claude_5_rows_include_aliases() -> None:
    """Explicit Claude 5 models should be pickable with their short aliases."""
    rows = build_model_rows()
    expected = {
        "claude-opus-5": "opus5",
        "claude-sonnet-5": "sonnet5",
        "claude-haiku-4-5": "haiku45",
    }

    for model_id, alias in expected.items():
        row = next(row for row in rows if row.option_id == model_id)
        assert row.provider == "claude"
        assert row.model_id == model_id
        assert row.alias == alias
        assert row.label == f"    {model_id}  ({alias})"
