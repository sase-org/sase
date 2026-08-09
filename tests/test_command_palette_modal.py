"""Tests for the command palette modal (Phase 2).

Covers the modal-level UX requirements from
``sdd/plans/202604/tui_command_palette.md`` Phase 2 acceptance:

- The modal renders with a non-empty applicable command list.
- Filtering narrows the list deterministically; ranking prefers
  prefix matches on label, then substring matches, then key/alias/
  category/id matches.
- Pure ``filter_specs`` produces stable output (catalog order is
  preserved on score ties).
- Enter returns the highlighted command id.
- Esc returns ``None``.
- The empty state is shown when no command matches.
- Up/Down/Ctrl+P/Ctrl+N navigate the list while the filter input
  retains focus.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.commands import (
    CommandExecutor,
    CommandPaletteResult,
    CommandSpec,
    build_command_catalog,
    is_command_available,
)
from sase.ace.tui.commands.types import CommandContext
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.command_palette_modal import (
    COMMAND_PALETTE_INPUT_HINT,
    CommandPaletteModal,
    _build_count_text,
    _build_position_text,
    _build_row_text,
    _filter_specs as filter_specs,
    _render_gauge,
    _score_match,
)


class _TestApp(App[CommandPaletteResult | None]):
    """Minimal app harness for async modal tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


# --- Fixture helpers ---


def _spec(
    spec_id: str,
    label: str,
    *,
    key_display: str = "x",
    key_sequence: tuple[str, ...] = ("x",),
    category: str = "Misc",
    aliases: tuple[str, ...] = (),
) -> CommandSpec:
    return CommandSpec(
        id=spec_id,
        label=label,
        key_sequence=key_sequence,
        key_display=key_display,
        category=category,  # type: ignore[arg-type]
        tabs=("changespecs", "agents", "axe"),  # legacy tab id
        executor=CommandExecutor(kind="app_action", action="quit"),
        aliases=aliases,
    )


def _live_specs() -> list[CommandSpec]:
    """Build an applicable list from the real catalog for the Patches tab.

    The Phase 3 wiring will pass exactly this kind of pre-filtered list
    in. Using the real catalog keeps the modal honest about real ids.
    """
    reg = load_keymap_registry({})
    catalog = build_command_catalog(reg)
    ctx = CommandContext(tab="changespecs")  # legacy tab id
    return [s for s in catalog if is_command_available(s, ctx)]


def _static_text(modal: CommandPaletteModal, selector: str) -> str:
    return str(modal.query_one(selector, Static).render())


# --- _score_match / filter_specs ---


def test_score_match_zero_when_no_match() -> None:
    s = _spec("app.refresh", "Refresh tab")
    assert _score_match(s, "zzznever") == 0


def test_score_match_prefix_outranks_substring() -> None:
    a = _spec("app.refresh", "Refresh tab")
    b = _spec("app.kill_agent", "Kill / dismiss agent (refresh)")
    sa = _score_match(a, "refresh")
    sb = _score_match(b, "refresh")
    assert sa > sb


def test_score_match_label_outranks_key() -> None:
    label_match = _spec("app.next", "Next entry", key_display="z")
    key_match = _spec("app.kill_agent", "Kill agent", key_display="next")
    assert _score_match(label_match, "next") > _score_match(key_match, "next")


def test_score_match_alias_substring() -> None:
    s = _spec("app.refresh", "Refresh tab", aliases=("reload",))
    assert _score_match(s, "reload") > 0


def test_score_match_empty_query_is_truthy() -> None:
    s = _spec("app.refresh", "Refresh tab")
    assert _score_match(s, "") > 0


def test_filter_specs_is_stable_on_ties() -> None:
    a = _spec("app.a", "Alpha")
    b = _spec("app.b", "Bravo")
    c = _spec("app.c", "Alpha-2")
    out = filter_specs([a, b, c], "alpha")
    # Both a and c have the same prefix-match score; catalog order
    # decides their relative order.
    assert [s.id for s in out] == ["app.a", "app.c"]


def test_filter_specs_excludes_non_matches() -> None:
    a = _spec("app.refresh", "Refresh tab")
    b = _spec("app.kill_agent", "Kill agent")
    out = filter_specs([a, b], "refresh")
    assert [s.id for s in out] == ["app.refresh"]


def test_filter_specs_empty_query_returns_all_in_order() -> None:
    a = _spec("app.refresh", "Refresh")
    b = _spec("app.next", "Next")
    out = filter_specs([a, b], "")
    assert [s.id for s in out] == ["app.refresh", "app.next"]


def test_filter_specs_key_filter_matches_raw_keys_and_chords() -> None:
    a = _spec("app.down", "Move down", key_display="j", key_sequence=("j",))
    b = _spec(
        "leader.jump",
        "Jump to notification",
        key_display=",j",
        key_sequence=("comma", "j"),
    )
    c = _spec("app.journal", "Journal", key_display="x", key_sequence=("x",))

    out = filter_specs([a, b, c], "key:j")
    assert [s.id for s in out] == ["app.down", "leader.jump"]


def test_filter_specs_key_filter_matches_display_chord() -> None:
    a = _spec(
        "leader.agent_run_log",
        "Agent run log",
        key_display=",A",
        key_sequence=("comma", "A"),
    )
    b = _spec("app.task", "Task list", key_display="x", key_sequence=("x",))

    out = filter_specs([a, b], "key:,A")
    assert [s.id for s in out] == ["leader.agent_run_log"]


def test_filter_specs_key_filter_matches_app_binding_alternatives() -> None:
    a = _spec(
        "app.open_command_palette",
        "Open command palette",
        key_display=": / ;",
        key_sequence=("colon,semicolon",),
    )
    b = _spec("app.refresh", "Refresh", key_display="r", key_sequence=("r",))

    assert [s.id for s in filter_specs([a, b], "key::")] == ["app.open_command_palette"]
    assert [s.id for s in filter_specs([a, b], "key:semicolon")] == [
        "app.open_command_palette"
    ]


def test_filter_specs_key_filter_does_not_match_text_metadata() -> None:
    a = _spec(
        "app.refresh",
        "Refresh tab",
        key_display="r",
        key_sequence=("r",),
        category="Display",
        aliases=("reload",),
    )

    assert filter_specs([a], "key:refresh") == []
    assert filter_specs([a], "key:display") == []
    assert filter_specs([a], "key:reload") == []


def test_filter_specs_key_filter_prefix_is_case_insensitive() -> None:
    a = _spec("app.quit", "Quit", key_display="Ctrl+D", key_sequence=("ctrl+d",))
    b = _spec("app.refresh", "Refresh", key_display="r", key_sequence=("r",))

    out = filter_specs([a, b], " KEY:ctrl+d ")
    assert [s.id for s in out] == ["app.quit"]


def test_filter_specs_bare_key_filter_returns_all_in_order() -> None:
    a = _spec("app.refresh", "Refresh")
    b = _spec("app.next", "Next")
    out = filter_specs([a, b], " key: ")
    assert [s.id for s in out] == ["app.refresh", "app.next"]


# --- _build_row_text ---


def test_build_row_text_includes_key_label_and_category() -> None:
    s = _spec("app.refresh", "Refresh tab", key_display="r", category="Display")
    text = _build_row_text(s).plain
    assert "r" in text
    assert "Refresh tab" in text
    assert "[Display]" in text


# --- count / position helpers ---


def test_build_count_text_unfiltered_plural() -> None:
    assert _build_count_text(72, 72).plain == "72 commands"


def test_build_count_text_filtered_plural() -> None:
    assert _build_count_text(12, 72).plain == "12 of 72 commands"


def test_build_count_text_singular() -> None:
    assert _build_count_text(1, 1).plain == "1 command"
    assert _build_count_text(0, 1).plain == "0 of 1 command"


def test_render_gauge_top_middle_bottom() -> None:
    top, top_idx = _render_gauge(1, 9, 9)
    middle, middle_idx = _render_gauge(5, 9, 9)
    bottom, bottom_idx = _render_gauge(9, 9, 9)

    assert top_idx == 0
    assert top == "●━━━━━━━━"
    assert middle_idx == 4
    assert middle == "━━━━●━━━━"
    assert bottom_idx == 8
    assert bottom == "━━━━━━━━●"


def test_render_gauge_handles_single_and_empty_totals() -> None:
    single, single_idx = _render_gauge(1, 1, 9)
    empty, empty_idx = _render_gauge(1, 0, 9)

    assert single_idx == 0
    assert single == "●━━━━━━━━"
    assert empty_idx == -1
    assert empty == "━━━━━━━━━"


def test_render_gauge_clamps_position_to_range() -> None:
    low, low_idx = _render_gauge(-10, 9, 9)
    high, high_idx = _render_gauge(99, 9, 9)

    assert low_idx == 0
    assert high_idx == 8
    assert 0 <= low_idx < 9
    assert 0 <= high_idx < 9
    assert low == "●━━━━━━━━"
    assert high == "━━━━━━━━●"


def test_build_position_text_contains_fraction_and_accent_style() -> None:
    text = _build_position_text(5, 72, "#87D7FF")

    assert "5/72" in text.plain
    styles = [str(span.style).lower() for span in text.spans]
    assert any("bold" in style and "#87d7ff" in style for style in styles)


# --- modal: rendering & content ---


async def test_modal_renders_nonempty_applicable_list() -> None:
    specs = _live_specs()
    assert specs, "expected applicable specs on the patches tab"

    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#command-palette-list", OptionList)
        assert option_list.option_count == len(specs)


async def test_modal_focuses_input_on_mount() -> None:
    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(
            specs=[_spec("app.refresh", "Refresh tab")],
            tab="changespecs",  # legacy tab id
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        assert filter_input.has_focus


async def test_modal_renders_key_filter_hint() -> None:
    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(
            specs=[_spec("app.refresh", "Refresh tab")],
            tab="changespecs",  # legacy tab id
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        hint = modal.query_one("#command-palette-input-hint", Static)
        assert hint.content == COMMAND_PALETTE_INPUT_HINT
        assert "key:<key>" in COMMAND_PALETTE_INPUT_HINT
        assert "key:j" in COMMAND_PALETTE_INPUT_HINT


async def test_modal_title_includes_tab_badge() -> None:
    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(
            specs=[_spec("app.refresh", "Refresh tab")],
            tab="agents",
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        title = modal._build_title().plain
        assert "Command Palette" in title
        assert "Agents" in title
        assert "1 command" in title


# --- modal: filtering ---


async def test_modal_filtering_narrows_list() -> None:
    specs = [
        _spec("app.refresh", "Refresh tab"),
        _spec("app.kill_agent", "Kill agent"),
        _spec("app.next", "Next entry"),
    ]
    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "kill"
        await pilot.pause()

        option_list = modal.query_one("#command-palette-list", OptionList)
        assert option_list.option_count == 1
        assert modal._filtered_specs[0].id == "app.kill_agent"


async def test_modal_status_count_switches_to_filtered_form() -> None:
    specs = [
        _spec("app.git_status", "Git status"),
        _spec("app.git_branch", "Git branch"),
        _spec("app.refresh", "Refresh tab"),
    ]
    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="agents")
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert "3 commands" in _static_text(modal, "#command-palette-title")

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "git"
        await pilot.pause()

        assert "2 of 3 commands" in _static_text(modal, "#command-palette-title")
        assert "1/2" in _static_text(modal, "#command-palette-position")


async def test_modal_filtering_resets_highlight_to_top() -> None:
    specs = [
        _spec("app.refresh", "Refresh tab"),
        _spec("app.kill_agent", "Kill agent"),
        _spec("app.next", "Next entry"),
    ]
    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#command-palette-list", OptionList)
        option_list.highlighted = 2
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "n"  # narrows the list
        await pilot.pause()

        assert option_list.highlighted == 0


async def test_modal_empty_state_shown_when_no_match() -> None:
    specs = [_spec("app.refresh", "Refresh tab")]
    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "zzznoresult"
        await pilot.pause()

        empty = modal.query_one("#command-palette-empty")
        option_list = modal.query_one("#command-palette-list", OptionList)
        assert empty.display is True
        assert option_list.display is False


async def test_modal_status_empty_filter_shows_zero_position() -> None:
    specs = [_spec("app.refresh", "Refresh tab")]
    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "zzznoresult"
        await pilot.pause()

        assert "0 of 1 command" in _static_text(modal, "#command-palette-title")
        assert "0/0" in _static_text(modal, "#command-palette-position")


# --- modal: enter / escape ---


async def test_modal_enter_returns_highlighted_id() -> None:
    result: CommandPaletteResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: CommandPaletteResult | None) -> None:
            nonlocal result
            result = r

        specs = [
            _spec("app.refresh", "Refresh tab"),
            _spec("app.kill_agent", "Kill agent"),
        ]
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Default highlight is the first option ("app.refresh").
        await pilot.press("enter")
        await pilot.pause()

        assert result is not None
        assert result.selected_id == "app.refresh"


async def test_modal_enter_after_filter_returns_filtered_top() -> None:
    result: CommandPaletteResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: CommandPaletteResult | None) -> None:
            nonlocal result
            result = r

        specs = [
            _spec("app.refresh", "Refresh tab"),
            _spec("app.kill_agent", "Kill agent"),
        ]
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "kill"
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert result is not None
        assert result.selected_id == "app.kill_agent"


async def test_modal_escape_returns_none() -> None:
    result: CommandPaletteResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: CommandPaletteResult | None) -> None:
            nonlocal result
            r_actual: CommandPaletteResult | None = r
            result = r_actual

        modal = CommandPaletteModal(
            specs=[_spec("app.refresh", "Refresh tab")],
            tab="changespecs",  # legacy tab id
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert result is not None
        assert result.selected_id is None


async def test_modal_enter_with_no_results_is_noop() -> None:
    """Enter while no commands match should not dismiss the modal."""
    dismiss_count = 0

    async with _TestApp().run_test() as pilot:

        def on_dismiss(_r: CommandPaletteResult | None) -> None:
            nonlocal dismiss_count
            dismiss_count += 1

        modal = CommandPaletteModal(
            specs=[_spec("app.refresh", "Refresh tab")],
            tab="changespecs",  # legacy tab id
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "zzznoresult"
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert dismiss_count == 0


# --- modal: navigation ---


async def test_modal_down_arrow_moves_highlight() -> None:
    specs = [
        _spec("app.a", "Alpha"),
        _spec("app.b", "Bravo"),
        _spec("app.c", "Charlie"),
    ]
    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#command-palette-list", OptionList)
        assert option_list.highlighted == 0

        await pilot.press("down")
        await pilot.pause()
        assert option_list.highlighted == 1

        await pilot.press("up")
        await pilot.pause()
        assert option_list.highlighted == 0


async def test_modal_position_updates_after_navigation() -> None:
    specs = [
        _spec("app.a", "Alpha"),
        _spec("app.b", "Bravo"),
        _spec("app.c", "Charlie"),
    ]
    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="agents")
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert "1/3" in _static_text(modal, "#command-palette-position")

        await pilot.press("down")
        await pilot.pause()
        assert "2/3" in _static_text(modal, "#command-palette-position")

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert "3/3" in _static_text(modal, "#command-palette-position")


async def test_modal_ctrl_n_ctrl_p_navigate() -> None:
    specs = [
        _spec("app.a", "Alpha"),
        _spec("app.b", "Bravo"),
    ]
    async with _TestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#command-palette-list", OptionList)

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert option_list.highlighted == 1

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert option_list.highlighted == 0


async def test_modal_typing_q_does_not_cancel() -> None:
    """Typing 'q' should go into the filter, not dismiss the modal."""
    dismiss_count = 0

    async with _TestApp().run_test() as pilot:

        def on_dismiss(_r: CommandPaletteResult | None) -> None:
            nonlocal dismiss_count
            dismiss_count += 1

        specs = [
            _spec("app.quit", "Quit ace"),
            _spec("app.refresh", "Refresh tab"),
        ]
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("q")
        await pilot.pause()

        assert dismiss_count == 0
        filter_input = modal.query_one("#command-palette-filter-input", Input)
        assert filter_input.value == "q"
