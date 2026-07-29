"""Tests for soft live completion in the prompt input."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_completion import (
    PromptCompletionSettings,
    build_prompt_soft_completion,
    parse_prompt_completion_settings,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
)

from ._completion_helpers import (
    CatalogCompletionTestApp,
    CompletionTestApp,
    registered_project_xprompts,
)


class RecordingCompletionTestApp(CompletionTestApp):
    """Completion test app that records submitted prompt values."""

    def __init__(self, snippets: dict[str, str] | None = None) -> None:
        super().__init__(snippets=snippets)
        self.submitted: list[str] = []

    def on_prompt_input_bar_submitted(
        self,
        message: PromptInputBar.Submitted,
    ) -> None:
        self.submitted.append(message.value)


def _input(
    name: str,
    type_: str,
    *,
    position: int = 0,
) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=True,
        default_display=None,
        position=position,
    )


def _entry(
    name: str,
    *,
    prefix: str = "#",
    inputs: tuple[XPromptInputHint, ...] = (),
    is_skill: bool = False,
) -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=name,
        insertion=f"{prefix}{name}",
        reference_prefix=prefix,
        kind="xprompt",
        input_signature=None,
        inputs=inputs,
        content_preview=None,
        is_skill=is_skill,
    )


def _seed_entries(
    ta: PromptTextArea,
    entries: list[XPromptAssistEntry],
    project: str | None = None,
) -> None:
    ta._xprompt_arg_assist_entries_by_project[project] = entries


def _compute_soft_now(ta: PromptTextArea) -> None:
    ta._clear_soft_completion(cancel_timer=True)
    ta._prompt_completion_generation += 1
    generation = ta._prompt_completion_generation
    ta._fire_prompt_completion_timer(
        generation,
        ta.text,
        ta._absolute_offset(ta.cursor_location),
    )


def test_prompt_completion_settings_parse_defaults_and_off_modes() -> None:
    assert parse_prompt_completion_settings({}) == PromptCompletionSettings()
    assert parse_prompt_completion_settings({}).auto_directive_menu is True
    assert parse_prompt_completion_settings({}).auto_artifact_menu is True
    assert parse_prompt_completion_settings({"auto": False}).auto == "off"
    assert parse_prompt_completion_settings({"auto": "soft"}).auto == "soft"
    parsed = parse_prompt_completion_settings(
        {
            "debounce_ms": "-1",
            "auto_file_paths": True,
            "auto_xprompt_menu": False,
            "auto_directive_menu": False,
            "auto_artifact_menu": False,
            "max_auto_rows": "0",
            "history_word_count": "25",
            "common_placeholder_count": "-5",
            "word_min_length": "0",
        }
    )
    assert parsed.debounce_ms == 0
    assert parsed.auto_file_paths is True
    assert parsed.auto_xprompt_menu is False
    assert parsed.auto_directive_menu is False
    assert parsed.auto_artifact_menu is False
    assert parsed.max_auto_rows == 1
    assert parsed.history_word_count == 25
    # A negative cap clamps to the ``0`` disable rather than going negative.
    assert parsed.common_placeholder_count == 0
    assert parsed.word_min_length == 1

    garbage = parse_prompt_completion_settings(
        {
            "history_word_count": "many",
            "common_placeholder_count": "lots",
            "word_min_length": None,
        }
    )
    assert garbage.history_word_count == 10000
    assert garbage.common_placeholder_count == 100
    assert garbage.word_min_length == 5
    assert (
        parse_prompt_completion_settings({"history_word_min_length": 2}).word_min_length
        == 5
    )


def test_xprompt_soft_builder_uses_warm_entries_only() -> None:
    entries = [_entry("review")]
    with patch(
        "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
        side_effect=AssertionError("cold catalog build"),
    ):
        suggestion = build_prompt_soft_completion(
            text="#r",
            cursor_offset=2,
            settings=PromptCompletionSettings(),
            xprompt_entries=entries,
        )
        cold = build_prompt_soft_completion(
            text="#r",
            cursor_offset=2,
            settings=PromptCompletionSettings(),
            xprompt_entries=None,
        )

    assert suggestion is not None
    assert suggestion.display == "#review"
    assert cold is None


async def test_soft_xprompt_suggestion_accepts_with_ctrl_l_not_enter() -> None:
    app = RecordingCompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("review", inputs=(_input("path", "path"),))])

        ta.load_text("#r")
        ta.cursor_location = (0, 2)
        _compute_soft_now(ta)

        assert bar.border_subtitle == "[^L] accept #review"
        await pilot.press("enter")
        assert app.submitted == ["#r"]
        assert ta._soft_completion is None

        ta.load_text("#r")
        ta.cursor_location = (0, 2)
        _compute_soft_now(ta)
        await pilot.press("ctrl+l")

    assert ta.text == "#review:"
    assert ta._active_xprompt_arg_hint is not None


async def test_soft_xprompt_required_text_accept_adds_double_colon_space() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("ask", inputs=(_input("body", "text"),))])

        ta.load_text("#a")
        ta.cursor_location = (0, 2)
        _compute_soft_now(ta)
        await pilot.press("ctrl+l")

    # Soft-accepting a single required-text xprompt at end-of-line widens the
    # ``::`` skeleton to the free-form ``:: `` shorthand.
    assert ta.text == "#ask:: "
    assert ta.cursor_location == (0, len("#ask:: "))


async def test_soft_xprompt_without_inputs_skips_space_before_punctuation() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("review")])

        ta.load_text("(#r)")
        ta.cursor_location = (0, len("(#r"))
        _compute_soft_now(ta)
        await pilot.press("ctrl+l")

    assert ta.text == "(#review)"
    assert ta.cursor_location == (0, len("(#review"))
    assert ta._active_xprompt_arg_hint is None


async def test_soft_xprompt_before_period_preserves_period() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("review")])

        ta.load_text("(see #r.")
        ta.cursor_location = (0, len("(see #r"))
        _compute_soft_now(ta)
        await pilot.press("ctrl+l")

    assert ta.text == "(see #review."
    assert ta.cursor_location == (0, len("(see #review"))
    assert ta._active_xprompt_arg_hint is None


async def test_ctrl_l_accepts_warm_xprompt_suggestion_before_debounce() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("review", inputs=(_input("path", "path"),))])
        prefix = "please inspect the wrapped prompt context " * 8
        text = f"{prefix}#r"

        ta.load_text(text)
        ta.cursor_location = (0, len(text))
        ta._on_prompt_completion_context_changed()

        assert ta._soft_completion is None
        assert ta._prompt_completion_timer is not None
        await pilot.press("ctrl+l")

    assert ta.text == f"{prefix}#review:"
    assert ta._active_xprompt_arg_hint is not None


async def test_ctrl_l_cold_xprompt_cache_schedules_warm_without_sync_build() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#r")
        ta.cursor_location = (0, 2)
        ta._on_prompt_completion_context_changed()

        with patch(
            "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
            side_effect=AssertionError("cold catalog build"),
        ):
            await pilot.press("ctrl+l")

    assert ta.text == "#r"
    assert ta._active_xprompt_arg_hint is None


async def test_soft_directive_suggestion_replaces_only_with_ctrl_l() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("%mo")
        ta.cursor_location = (0, 3)
        _compute_soft_now(ta)

        assert bar.border_subtitle == "[^L] accept %model"
        await pilot.press("ctrl+l")

    assert ta.text == "%model"
    assert ta._file_completion_active is False


async def test_soft_xprompt_arg_name_and_bool_value_suggestions() -> None:
    entry = _entry(
        "review",
        inputs=(
            _input("path", "path", position=0),
            _input("enabled", "bool", position=1),
        ),
    )
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [entry])

        ta.load_text("#review(e")
        ta.cursor_location = (0, len("#review(e"))
        _compute_soft_now(ta)
        assert bar.border_subtitle == "[^L] accept enabled="
        await pilot.press("ctrl+l")
        assert ta.text == "#review(enabled="

        ta.load_text("#review(enabled=)")
        ta.cursor_location = (0, len("#review(enabled="))
        _compute_soft_now(ta)
        assert bar.border_subtitle == "[^L] accept true"
        await pilot.press("ctrl+l")

    assert ta.text == "#review(enabled=true)"


async def test_soft_completion_does_not_hide_ctrl_t_panel_path() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_entry("review"), _entry("ship")])
        ta.load_text("#")
        ta.cursor_location = (0, 1)
        _compute_soft_now(ta)
        assert ta._soft_completion is not None

        await pilot.press("ctrl+t")

        panel = bar.query_one("#prompt-completion", Static)
        assert ta._soft_completion is None
        assert ta._file_completion_active is True
        assert panel.border_title == "xprompts"
        assert "#review" in panel.render().plain


async def test_cold_cache_auto_completion_does_not_build_catalog_sync() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("#r")
        ta.cursor_location = (0, 2)

        with patch(
            "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
            side_effect=AssertionError("cold catalog build"),
        ):
            _compute_soft_now(ta)

    assert ta._soft_completion is None


async def test_soft_xprompt_suggestion_uses_canonical_project_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``<ctrl+l>`` must agree with the menu on the project namespace.

    The prompt context supplies a ProjectSpec directory key, so without
    normalization the soft builder asks the catalog for a project spelling it
    can never match and no suggestion is offered.
    """
    app = CatalogCompletionTestApp()
    with registered_project_xprompts(
        tmp_path,
        monkeypatch,
        project_key="gh_org__proj",
        project_name="proj",
        xprompts={"reads": "Reads body", "sync": "Sync body"},
    ):
        async with app.run_test() as pilot:
            bar = app.query_one(PromptInputBar)
            ta = app.query_one(PromptTextArea)
            app._prompt_context = SimpleNamespace(
                project_name="gh_org__proj",
                is_home_mode=False,
            )

            ta.load_text("#proj/r")
            ta.cursor_location = (0, 7)
            _compute_soft_now(ta)
            subtitle = bar.border_subtitle

            await pilot.press("ctrl+l")

    assert subtitle == "[^L] accept #proj/reads"
    assert ta.text == "#proj/reads "
    assert app.requested_projects == ["proj"] * len(app.requested_projects)
    assert app.requested_projects
