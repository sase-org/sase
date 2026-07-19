"""Tests for the model picker modal."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Input, OptionList, Static

from rich.text import Text

from sase.ace.tui.provider_styles import _provider_style_for
from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    DEFAULT_SENTINEL,
    AliasSelectionContext,
    ModelPickerModal,
    alias_reference_rejection,
)
from sase.ace.tui.modals.model_picker_options import (
    build_model_options,
    rows_to_options,
)
from sase.ace.tui.modals.model_picker_rows import (
    ModelPickerRow,
    _alias_disabled_reason,
    build_model_rows,
)
from tests._models_panel_helpers import make_alias_view, make_override

_ROOT = Path(__file__).resolve().parents[1]


class _TestApp(App[str | None]):
    """Minimal app for async model picker tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class _StyledTestApp(_TestApp):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"


def _alias_context(
    *,
    target: str = "big_epic_lander",
    operation: str = "persistent",
    views=None,
) -> AliasSelectionContext:
    if views is None:
        views = [
            make_alias_view(
                "default",
                "default",
                provider="claude",
                model="opus",
                description="Default launch model.",
            ),
            make_alias_view(
                "coder",
                "role",
                provider="codex",
                model="gpt-5.6-sol",
                description="Implementation follow-up agents.",
            ),
            make_alias_view("epic_lander", "role", provider="claude", model="opus"),
            make_alias_view("big_epic_lander", "role", provider="claude", model="opus"),
            make_alias_view("phase_worker", "role", provider="claude", model="sonnet"),
        ]
    return AliasSelectionContext(
        views=tuple(views),
        target_alias=target,
        operation=operation,  # type: ignore[arg-type]
    )


def _highlighted_id(option_list: OptionList) -> str | None:
    highlighted = option_list.highlighted
    if highlighted is None:
        return None
    option = option_list.get_option_at_index(highlighted)
    return str(option.id) if option.id is not None else None


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


def test_alias_context_builds_ordered_styled_rows_before_models() -> None:
    context = _alias_context(target="phase_worker")
    rows = build_model_rows(
        include_default_option=False,
        alias_context=context,
    )

    assert [row.option_id for row in rows[:6]] == [
        "__header_aliases__",
        "@default",
        "@coder",
        "@epic_lander",
        "@big_epic_lander",
        "@phase_worker",
    ]
    assert next(row for row in rows if row.kind == "provider").option_id.startswith(
        "__header_"
    )
    alias_options = [
        option
        for option in rows_to_options(rows[:6])
        if option is not None and str(option.id).startswith("@")
    ]
    assert all(isinstance(option.prompt, Text) for option in alias_options)
    assert {option.prompt.plain.index("→") for option in alias_options} == {27}
    coder = next(option for option in alias_options if option.id == "@coder")
    assert "CODEX(gpt-5.6-sol)" in coder.prompt.plain
    assert any(span.style == "bold #87D7FF" for span in coder.prompt.spans)


def test_alias_dependency_guard_covers_implicit_and_configured_chains() -> None:
    views = [
        make_alias_view("default", "default"),
        make_alias_view("coder", "role"),
        make_alias_view("codex_coder", "provider_coder"),
        make_alias_view("epic_lander", "role"),
        make_alias_view("big_epic_lander", "role"),
        make_alias_view("hop_a", "user", configured=True, configured_value="@hop_b"),
        make_alias_view("hop_b", "user", configured=True, configured_value="@coder"),
        make_alias_view(
            "cycle_a", "user", configured=True, configured_value="@cycle_b"
        ),
        make_alias_view(
            "cycle_b", "user", configured=True, configured_value="@cycle_a"
        ),
        make_alias_view(
            "safe", "user", configured=True, configured_value="claude/haiku"
        ),
    ]
    coder_context = _alias_context(target="coder", views=views)
    default_context = _alias_context(target="default", views=views)

    assert _alias_disabled_reason(coder_context, "coder") == "current alias"
    assert _alias_disabled_reason(coder_context, "hop_a") == "would create a cycle"
    assert _alias_disabled_reason(coder_context, "cycle_a") == ("would create a cycle")
    assert _alias_disabled_reason(coder_context, "safe") is None
    # provider_coder -> coder -> default and
    # big_epic_lander -> epic_lander -> default are implicit chains.
    assert _alias_disabled_reason(default_context, "codex_coder") == (
        "would create a cycle"
    )
    assert _alias_disabled_reason(default_context, "big_epic_lander") == (
        "would create a cycle"
    )


def test_alias_dependency_guard_handles_long_chains() -> None:
    views = [make_alias_view("target", "user")]
    for index in range(40):
        dependency = "target" if index == 39 else f"hop_{index + 1}"
        views.append(
            make_alias_view(
                f"hop_{index}",
                "user",
                configured=True,
                configured_value=f"@{dependency}",
            )
        )
    context = _alias_context(target="target", views=views)

    assert _alias_disabled_reason(context, "hop_0") == "would create a cycle"


def test_temporary_alias_guard_disables_only_self() -> None:
    views = [
        make_alias_view("target", "user"),
        make_alias_view(
            "cycle_a", "user", configured=True, configured_value="@cycle_b"
        ),
        make_alias_view(
            "cycle_b", "user", configured=True, configured_value="@cycle_a"
        ),
    ]
    context = _alias_context(target="target", operation="temporary", views=views)

    assert _alias_disabled_reason(context, "target") == "current alias"
    assert _alias_disabled_reason(context, "cycle_a") is None


def test_free_form_alias_guard_rejects_unknown_and_unsafe_references() -> None:
    context = _alias_context(target="coder")

    assert alias_reference_rejection(context, "@missing") == "unknown alias"
    assert alias_reference_rejection(context, "@coder") == "current alias"
    assert alias_reference_rejection(context, "@default") is None
    assert alias_reference_rejection(context, "claude/opus") is None


async def test_alias_picker_filters_all_alias_fields_and_returns_raw_token() -> None:
    captured: list[str | None] = []
    context = _alias_context(target="phase_worker")

    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal(
            include_default_option=False,
            alias_context=context,
        )
        pilot.app.push_screen(modal, captured.append)
        await pilot.pause()
        filter_input = modal.query_one("#model-picker-filter", Input)
        assert filter_input.placeholder == "Filter aliases, providers, or models..."

        for query in ("@coder", "coder", "implementation follow-up", "gpt-5.6"):
            filter_input.value = query
            await pilot.pause()
            ids = {
                option.id
                for option in modal.query_one("#model-picker-list", OptionList).options
            }
            assert "@coder" in ids
            assert "__empty__" not in ids

        option_list = modal.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index("@coder")
        modal.action_select_model()
        await pilot.pause()

    assert captured == ["@coder"]


async def test_alias_only_no_match_uses_contextual_empty_state() -> None:
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal(
            include_default_option=False,
            alias_context=_alias_context(),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal.query_one("#model-picker-filter", Input).value = "not-a-target"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        empty = option_list.get_option("__empty__")
        assert str(empty.prompt) == "  No matching aliases or models"
        assert option_list.get_option(CUSTOM_SENTINEL) is not None


async def test_alias_disabled_rows_are_searchable_and_skipped_by_navigation() -> None:
    context = _alias_context(target="coder")
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal(
            include_default_option=False,
            alias_context=context,
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "@coder"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        coder = option_list.get_option("@coder")
        assert coder.disabled is True
        assert "current alias" in str(coder.prompt)
        assert "@coder" not in modal._visible_selectable_option_ids()
        modal.action_jump_to_entry()
        assert "@coder" not in modal._model_jump_id_to_hint


async def test_alias_picker_narrow_geometry_keeps_single_line_rows_and_footer() -> None:
    long_name = "very_long_custom_alias_name_that_must_truncate"
    context = _alias_context(
        target="phase_worker",
        views=[
            make_alias_view(
                long_name,
                "user",
                configured=True,
                configured_value="opencode/anthropic/claude-sonnet-4-5",
                provider="opencode",
                model="anthropic/claude-sonnet-4-5",
            ),
            make_alias_view("phase_worker", "role"),
        ],
    )
    async with _StyledTestApp().run_test(size=(60, 30)) as pilot:
        modal = ModelPickerModal(
            include_default_option=False,
            alias_context=context,
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        container = modal.query_one("#model-picker-container", Container)
        footer = modal.query_one("#model-picker-footer", Static)
        option = modal.query_one("#model-picker-list", OptionList).get_option(
            f"@{long_name}"
        )
        assert container.region.x >= 0
        assert container.region.right <= modal.size.width
        assert footer.region.bottom <= modal.size.height
        assert isinstance(option.prompt, Text)
        assert "\n" not in option.prompt.plain
        assert option.prompt.no_wrap is True


async def test_model_picker_returns_none_for_default() -> None:
    """Selecting 'Follow-up default' returns None."""
    result: str | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # First option is "Follow-up default" — select it
        await pilot.press("enter")
        await pilot.pause()

        assert result is None


async def test_model_picker_distinct_default_returns_sentinel() -> None:
    """With distinct_default, selecting the default returns DEFAULT_SENTINEL."""
    result: str | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal(distinct_default=True)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # First option is "Follow-up default" — select it
        await pilot.press("enter")
        await pilot.pause()

        assert result == DEFAULT_SENTINEL


async def test_model_picker_distinct_default_escape_still_returns_none() -> None:
    """Escape still cancels (None) even when distinct_default is enabled."""
    result: str | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal(distinct_default=True)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert result is None


async def test_model_picker_escape_cancels() -> None:
    """Escape returns None (cancel)."""
    result: str | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert result is None


async def test_model_picker_returns_model_string() -> None:
    """Selecting a model returns its name string."""
    result: str | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        # Navigate down past default + separator + header to first model (opus)
        # Default (0) -> separator -> CLAUDE header (disabled) -> opus
        option_list.highlighted = option_list.get_option_index("opus")
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert result == "opus"


async def test_model_picker_returns_custom_sentinel() -> None:
    """Selecting 'Custom...' returns the custom sentinel."""
    result: str | None = "not_set"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index(CUSTOM_SENTINEL)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert result == CUSTOM_SENTINEL


async def test_model_picker_vim_navigation() -> None:
    """j/k keys should navigate the option list."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        initial = option_list.highlighted

        # j moves down
        await pilot.press("j")
        await pilot.pause()
        after_j = option_list.highlighted
        assert after_j != initial

        # k moves back up
        await pilot.press("k")
        await pilot.pause()
        after_k = option_list.highlighted
        assert after_k == initial


async def test_model_picker_filters_by_provider() -> None:
    """Provider filters should show that provider's full model group."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "codex"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        ids = {option.id for option in option_list.options}
        assert "__header_codex__" in ids
        assert "o3" in ids
        assert "gpt-5.6-sol" in ids
        assert "gpt-5.5" in ids
        assert "__header_agy__" not in ids


async def test_model_picker_filters_by_model_substring() -> None:
    """Model substring filters should keep matching models and their header."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "Flash (High)"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        ids = {option.id for option in option_list.options}
        assert "__header_agy__" in ids
        assert "Gemini 3.5 Flash (High)" in ids
        assert "Gemini 3.5 Flash (Low)" not in ids


async def test_model_picker_filters_by_alias() -> None:
    """Short aliases from provider metadata should be searchable."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "sonnet45"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        ids = {option.id for option in option_list.options}
        assert "__header_opencode__" in ids
        assert "anthropic/claude-sonnet-4-5" in ids


async def test_model_picker_no_results_keeps_escape_hatches() -> None:
    """No-results rendering should keep default/custom paths available."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "definitely-no-such-model"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        ids = {option.id for option in option_list.options}
        labels = [str(option.prompt) for option in option_list.options]
        assert "__default__" in ids
        assert CUSTOM_SENTINEL in ids
        assert "__empty__" in ids
        assert "  No matching models" in labels


async def test_model_picker_selection_remains_valid_after_filter_change() -> None:
    """Filtering away the highlighted model should move selection to a visible row."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index("o3")
        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "gemini"
        await pilot.pause()

        highlighted = option_list.highlighted
        assert highlighted is not None
        option = option_list.get_option_at_index(highlighted)
        assert option.id != "o3"
        # A "gemini" filter matches the Antigravity (agy) "Gemini ..."
        # display-name models.
        assert "gemini" in str(option.id).lower()


async def test_model_picker_escape_clears_filter_before_cancel() -> None:
    """Escape clears an active filter before the modal cancel path."""
    result: str | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "codex"
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert filter_input.value == ""
        assert result == "sentinel"


async def test_model_picker_without_default_filters_correctly() -> None:
    """Temporary override callers should still omit the default option."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal(include_default_option=False)
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "codex"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        ids = {option.id for option in option_list.options}
        assert "__default__" not in ids
        assert CUSTOM_SENTINEL in ids
        assert "o3" in ids


async def test_model_picker_jump_hints_follow_filtered_visible_order() -> None:
    """Jump hints should be assigned in visible selectable-row order."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "gemini"
        await pilot.pause()

        modal.action_jump_to_entry()

        visible_ids = modal._visible_selectable_option_ids()
        # Providers render in entry-point order (alphabetical), so the
        # Antigravity (agy) "Gemini ..." display-name models lead the filtered
        # list.
        assert visible_ids[:3] == [
            "__default__",
            "Gemini 3.5 Flash (High)",
            "Gemini 3.5 Flash (Low)",
        ]
        assert modal._model_jump_hint_to_id["0"] == visible_ids[0]
        assert modal._model_jump_hint_to_id["1"] == visible_ids[1]
        assert modal._model_jump_id_to_hint[visible_ids[2]] == "2"


async def test_model_picker_jump_apostrophe_without_history_highlights_first() -> None:
    """Apostrophe in jump mode targets the first visible selectable row."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index(CUSTOM_SENTINEL)

        modal.action_jump_to_entry()
        handled = modal._handle_model_jump_key("apostrophe")

        assert handled is True
        assert _highlighted_id(option_list) == "__default__"
        assert modal._model_jump_last_id == CUSTOM_SENTINEL
        assert modal._model_jump_mode_active is False


async def test_model_picker_jump_apostrophe_back_highlights_previous() -> None:
    """Apostrophe in jump mode returns to the saved previous row."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        modal._model_jump_last_id = "o3"
        option_list.highlighted = option_list.get_option_index(CUSTOM_SENTINEL)

        modal.action_jump_to_entry()
        handled = modal._handle_model_jump_key("apostrophe")

        assert handled is True
        assert _highlighted_id(option_list) == "o3"
        assert modal._model_jump_last_id == CUSTOM_SENTINEL
        assert modal._model_jump_mode_active is False


async def test_model_picker_jump_accepts_uppercase_hint() -> None:
    """Uppercase hint characters should dispatch to their exact target."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        rows = [
            ModelPickerRow(
                kind="model",
                label=f"    synthetic-{index}",
                option_id=f"synthetic-{index}",
                provider="synthetic",
                model_id=f"synthetic-{index}",
            )
            for index in range(37)
        ]
        option_list = modal.query_one("#model-picker-list", OptionList)
        modal._visible_rows = rows
        option_list.clear_options()
        option_list.add_options(modal._render_options())
        option_list.highlighted = option_list.get_option_index("synthetic-0")

        modal.action_jump_to_entry()
        assert modal._model_jump_hint_to_id["A"] == "synthetic-36"
        handled = modal._handle_model_jump_key("A")

        assert handled is True
        assert _highlighted_id(option_list) == "synthetic-36"
        assert modal._model_jump_mode_active is False


async def test_model_picker_two_character_hint_accepts_uppercase_second_char() -> None:
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        rows = [
            ModelPickerRow(
                kind="model",
                label=f"    synthetic-{index}",
                option_id=f"synthetic-{index}",
                provider="synthetic",
                model_id=f"synthetic-{index}",
            )
            for index in range(63)
        ]
        option_list = modal.query_one("#model-picker-list", OptionList)
        modal._visible_rows = rows
        option_list.clear_options()
        option_list.add_options(modal._render_options())
        option_list.highlighted = option_list.get_option_index("synthetic-0")

        modal.action_jump_to_entry()
        assert modal._model_jump_hint_to_id["0Z"] == "synthetic-61"

        assert modal._handle_model_jump_key("0") is True
        assert modal._model_jump_mode_active is True
        assert modal._model_jump_pending_prefix == "0"
        assert _highlighted_id(option_list) == "synthetic-0"

        assert modal._handle_model_jump_key("Z") is True
        assert modal._model_jump_mode_active is False
        assert modal._model_jump_pending_prefix == ""
        assert _highlighted_id(option_list) == "synthetic-61"


async def test_model_picker_filter_change_clears_jump_hints() -> None:
    """Refiltering should leave no stale hint markers on hidden rows."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_jump_to_entry()
        assert modal._model_jump_mode_active is True

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "codex"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        assert modal._model_jump_mode_active is False
        assert modal._model_jump_pending_prefix == ""
        assert modal._model_jump_hint_to_id == {}
        assert all(
            not str(option.prompt).startswith("[")
            for option in option_list.options
            if option.id != "__empty__"
        )
