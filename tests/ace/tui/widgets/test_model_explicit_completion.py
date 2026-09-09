"""Tests for ``**model`` prompt model completion."""

from __future__ import annotations

from unittest.mock import patch

from textual.app import ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets._file_completion_workers import (
    ModelCompletionCatalogWorkerResult,
)
from sase.ace.tui.widgets.model_alias_completion import MODEL_ALIAS_COMPLETION_KIND
from sase.ace.tui.widgets.model_explicit_completion import (
    MODEL_EXPLICIT_COMPLETION_KIND,
    MODEL_EXPLICIT_MODE_SUBTITLE,
    build_model_explicit_completion_candidates,
    detect_model_explicit_completion_context,
    is_model_explicit_completion_placeholder,
    plan_model_explicit_completion_edit,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.model_completion import ModelCompletionEntry

from ._completion_helpers import CompletionTestApp


class _DefaultEntries:
    pass


_USE_DEFAULT = _DefaultEntries()


class ModelExplicitCompletionTestApp(CompletionTestApp):
    """Completion test app with a deterministic model catalog hook."""

    def __init__(
        self,
        *,
        entries: tuple[ModelCompletionEntry, ...] | None | _DefaultEntries = (
            _USE_DEFAULT
        ),
        settings: PromptCompletionSettings | None = None,
        available: bool = True,
        initial_panes: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.entries: tuple[ModelCompletionEntry, ...] | None = (
            _model_entries() if isinstance(entries, _DefaultEntries) else entries
        )
        self.settings = settings or PromptCompletionSettings()
        self.available = available
        self.initial_panes = initial_panes
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        if self.initial_panes is None:
            yield PromptInputBar()
            return
        yield PromptInputBar(initial_panes=self.initial_panes)

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings

    def model_completion_catalog(
        self,
    ) -> tuple[tuple[ModelCompletionEntry, ...] | None, bool]:
        return self.entries, self.available

    def on_prompt_input_bar_submitted(
        self,
        message: PromptInputBar.Submitted,
    ) -> None:
        self.submitted.append(message.value)


class ColdModelExplicitCompletionTestApp(CompletionTestApp):
    """Completion app without a synchronous model catalog provider."""

    def __init__(
        self,
        *,
        settings: PromptCompletionSettings | None = None,
        initial_panes: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings or PromptCompletionSettings()
        self.initial_panes = initial_panes
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        if self.initial_panes is None:
            yield PromptInputBar()
            return
        yield PromptInputBar(initial_panes=self.initial_panes)

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings

    def on_prompt_input_bar_submitted(
        self,
        message: PromptInputBar.Submitted,
    ) -> None:
        self.submitted.append(message.value)


def _model_entries() -> tuple[ModelCompletionEntry, ...]:
    return (
        ModelCompletionEntry(
            value="@large",
            display="@large",
            description="Large alias",
            kind="user_alias",
            alias_kind="user",
            aliases=("large",),
            target_provider="codex",
            target_model="gpt-5.6-sol",
            provenance="configured",
        ),
        ModelCompletionEntry(
            value="gpt-5.6-sol",
            display="gpt-5.6-sol",
            description="Codex (sol)",
            kind="model",
            provider="codex",
            provider_display="Codex",
            aliases=("sol", "gpt56sol"),
        ),
        ModelCompletionEntry(
            value="claude-fable-5",
            display="claude-fable-5",
            description="Claude (fable)",
            kind="model",
            provider="claude",
            provider_display="Claude",
            aliases=("fable",),
        ),
        ModelCompletionEntry(
            value="codex/",
            display="codex/",
            description="Codex",
            kind="provider",
            provider="codex",
            provider_display="Codex",
            provider_model_count=1,
        ),
        ModelCompletionEntry(
            value="opencode/",
            display="opencode/",
            description="OpenCode",
            kind="provider",
            provider="opencode",
            provider_display="OpenCode",
            provider_model_count=1,
        ),
        ModelCompletionEntry(
            value="anthropic/claude-sonnet-4-5",
            display="anthropic/claude-sonnet-4-5",
            description="OpenCode Anthropic",
            kind="model",
            provider="opencode",
            provider_display="OpenCode Anthropic",
        ),
    )


def _candidate_insertions(text_area: PromptTextArea) -> list[str]:
    return [candidate.insertion for candidate in text_area._file_completion_candidates]


def _selected_insertion(text_area: PromptTextArea) -> str:
    return text_area._file_completion_candidates[
        text_area._file_completion_index
    ].insertion


async def test_double_star_auto_opens_and_enter_expands_without_submit() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()

        await pilot.press("*")
        assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND

        await pilot.press("*")
        await pilot.press("g")

        panel = bar.query_one("#prompt-completion", Static)
        assert ta._file_completion_active is True
        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
        assert panel.border_title == "explicit models"
        assert _candidate_insertions(ta) == ["gpt-5.6-sol"]
        assert "Enter → %m:gpt-5.6-sol · Codex (sol)" in str(panel.border_subtitle)
        assert bar._subtitle_base == MODEL_EXPLICIT_MODE_SUBTITLE

        await pilot.press("enter")

        assert ta.text == "%m:gpt-5.6-sol "
        assert app.submitted == []
        assert ta._file_completion_active is False
        assert bar._subtitle_base == bar._mode_subtitle


def test_double_star_context_and_filtering_use_model_rows_only() -> None:
    context = detect_model_explicit_completion_context("Review **gp", (0, 11))

    assert context is not None
    assert context.query == "gp"
    assert context.token == "**gp"
    assert [
        candidate.insertion
        for candidate in build_model_explicit_completion_candidates(
            context,
            _model_entries(),
        )
    ] == ["gpt-5.6-sol"]

    scoped = detect_model_explicit_completion_context("Review **codex/g", (0, 16))
    assert scoped is not None
    assert [
        candidate.insertion
        for candidate in build_model_explicit_completion_candidates(
            scoped,
            _model_entries(),
        )
    ] == ["codex/gpt-5.6-sol"]

    short_hint = detect_model_explicit_completion_context("Review **fable", (0, 14))
    assert short_hint is not None
    assert [
        candidate.insertion
        for candidate in build_model_explicit_completion_candidates(
            short_hint,
            _model_entries(),
        )
    ] == ["claude-fable-5"]


async def test_double_star_ctrl_t_opens_when_auto_directive_menu_disabled() -> None:
    app = ModelExplicitCompletionTestApp(
        settings=PromptCompletionSettings(auto_directive_menu=False),
    )
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        await pilot.press("*")
        await pilot.press("g")
        assert ta._file_completion_active is False

        await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
        assert _candidate_insertions(ta) == ["gpt-5.6-sol"]


async def test_star_shortcut_switches_between_alias_and_model_in_manual_session() -> (
    None
):
    app = ModelExplicitCompletionTestApp(
        settings=PromptCompletionSettings(auto_directive_menu=False),
    )
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        await pilot.press("ctrl+t")
        assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
        assert _candidate_insertions(ta) == ["@large"]

        await pilot.press("*")
        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
        assert _candidate_insertions(ta) == [
            "gpt-5.6-sol",
            "claude-fable-5",
            "anthropic/claude-sonnet-4-5",
        ]
        ta._file_completion_index = 1

        await pilot.press("backspace")
        assert ta.text == "*"
        assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
        assert _candidate_insertions(ta) == ["@large"]
        assert ta._file_completion_index == 0


async def test_second_star_takes_over_when_alias_rows_are_empty() -> None:
    model_only_entries = tuple(
        entry for entry in _model_entries() if entry.kind == "model"
    )
    app = ModelExplicitCompletionTestApp(entries=model_only_entries)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        assert ta.text == "*"
        assert ta._file_completion_active is False

        await pilot.press("*")
        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
        assert _candidate_insertions(ta) == [
            "gpt-5.6-sol",
            "claude-fable-5",
            "anthropic/claude-sonnet-4-5",
        ]


async def test_second_star_takes_over_when_alias_catalog_is_loading() -> None:
    app = ModelExplicitCompletionTestApp(entries=None)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        with patch.object(type(ta), "_schedule_model_completion_catalog_load"):
            await pilot.press("*")
            assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
            assert ta._file_completion_candidates[0].display == (
                "Loading model aliases…"
            )

            await pilot.press("*")

        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
        assert ta._file_completion_candidates[0].display == "Loading models…"


async def test_double_star_navigation_preserves_selection_while_filtering() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        await pilot.press("*")
        assert _candidate_insertions(ta) == [
            "gpt-5.6-sol",
            "claude-fable-5",
            "anthropic/claude-sonnet-4-5",
        ]

        await pilot.press("down")
        assert _selected_insertion(ta) == "claude-fable-5"

        await pilot.press("c")
        assert ta.text == "**c"
        assert _candidate_insertions(ta) == ["claude-fable-5"]
        assert _selected_insertion(ta) == "claude-fable-5"

        await pilot.press("backspace")
        assert ta.text == "**"
        assert _candidate_insertions(ta) == [
            "gpt-5.6-sol",
            "claude-fable-5",
            "anthropic/claude-sonnet-4-5",
        ]
        assert _selected_insertion(ta) == "claude-fable-5"


async def test_double_star_ctrl_l_accepts_selection_without_submit_or_newline() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        await pilot.press("*")
        await pilot.press("f")
        await pilot.press("ctrl+l")

        assert ta.text == "%m:claude-fable-5 "
        assert "\n" not in ta.text
        assert app.submitted == []
        assert ta._file_completion_active is False


async def test_double_star_third_star_and_space_dismiss_completion() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        await pilot.press("*")
        await pilot.press("g")
        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND

        await pilot.press("*")
        assert ta.text == "**g*"
        assert ta._file_completion_active is False

        ta.load_text("**g")
        ta.cursor_location = (0, 3)
        assert ta._try_model_explicit_completion() is True
        assert ta._file_completion_active is True

        await pilot.press("space")
        assert ta.text == "**g "
        assert ta._file_completion_active is False


async def test_warm_double_star_typing_never_builds_catalog_on_key_path() -> None:
    app = ModelExplicitCompletionTestApp()
    with patch(
        "sase.ace.tui.widgets._file_completion_workers.build_model_completion_catalog",
        side_effect=AssertionError("cold catalog builder reached"),
    ):
        async with app.run_test() as pilot:
            ta = app.query_one(PromptInputBar).active_text_area()

            await pilot.press("*")
            await pilot.press("*")
            await pilot.press("g")
            await pilot.press("p")

            assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
            assert _candidate_insertions(ta) == ["gpt-5.6-sol"]


async def test_double_star_accept_replaces_whole_token_from_mid_token_cursor() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        ta.load_text("Use **gpX later")
        ta.cursor_location = (0, len("Use **gp"))

        await pilot.press("ctrl+t")
        await pilot.press("enter")

        assert ta.text == "Use %m:gpt-5.6-sol later"
        assert ta.cursor_location == (0, len("Use %m:gpt-5.6-sol "))
        assert app.submitted == []


async def test_double_star_accept_preserves_context_and_undo_redo() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        original = "Keep\t🙂 **gpX tail\nnext"
        expanded = "Keep\t🙂 %m:gpt-5.6-sol tail\nnext"
        ta.load_text(original)
        ta.cursor_location = (0, len("Keep\t🙂 **gp"))

        await pilot.press("ctrl+t")
        await pilot.press("enter")

        assert ta.text == expanded
        assert ta.cursor_location == (0, len("Keep\t🙂 %m:gpt-5.6-sol "))
        assert app.submitted == []

        await pilot.press("escape")
        await pilot.press("u")

        assert ta.text == original
        assert ta._file_completion_active is False

        await pilot.press("ctrl+r")

        assert ta.text == expanded
        assert ta._file_completion_active is False


def test_double_star_edit_plan_spacer_cases() -> None:
    cases = [
        ("Use **gp", (0, 8), "Use %m:gpt-5.6-sol ", "%m:gpt-5.6-sol "),
        ("Use **gp now", (0, 8), "Use %m:gpt-5.6-sol now", "%m:gpt-5.6-sol "),
        ("Use **gp\tnow", (0, 8), "Use %m:gpt-5.6-sol\tnow", "%m:gpt-5.6-sol"),
        (
            "Title\r\nUse **gp",
            (1, len("Use **gp")),
            "Title\r\nUse %m:gpt-5.6-sol ",
            "%m:gpt-5.6-sol ",
        ),
        ("🙂 **gp\r\nnext", (0, 6), "🙂 %m:gpt-5.6-sol \r\nnext", "%m:gpt-5.6-sol "),
    ]
    for text, cursor, expected_text, expected_replacement in cases:
        context = detect_model_explicit_completion_context(text, cursor)
        assert context is not None
        selected = build_model_explicit_completion_candidates(
            context,
            _model_entries(),
        )[0]
        planned = plan_model_explicit_completion_edit(
            text,
            cursor,
            _model_entries(),
            selected,
        )

        assert planned is not None
        assert planned.replacement == expected_replacement
        applied = (
            f"{text[: planned.replacement_start]}"
            f"{planned.replacement}"
            f"{text[planned.replacement_end :]}"
        )
        assert applied == expected_text
        assert planned.caret_offset == planned.replacement_start + len(
            planned.replacement
        )


async def test_unknown_double_star_stays_literal_and_can_submit() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        await pilot.press("*")
        await pilot.press("z")
        await pilot.press("z")

        assert ta.text == "**zz"
        assert ta._file_completion_active is False

        await pilot.press("enter")

        assert app.submitted == ["**zz"]


async def test_loading_model_rows_are_not_selectable() -> None:
    app = ModelExplicitCompletionTestApp(entries=None)
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptInputBar).active_text_area()
        ta.load_text("**")
        ta.cursor_location = (0, 2)

        with patch.object(type(ta), "_schedule_model_completion_catalog_load") as load:
            assert ta._try_model_explicit_completion() is True

        load.assert_called_once_with()
        assert is_model_explicit_completion_placeholder(
            ta._file_completion_candidates[0]
        )
        assert ta._file_completion_candidates[0].display == "Loading models…"
        assert bar._subtitle_base != MODEL_EXPLICIT_MODE_SUBTITLE

        await pilot.press("enter")

        assert ta.text == "**"
        assert app.submitted == []
        assert ta._file_completion_active is True


async def test_model_catalog_worker_refreshes_only_matching_shortcut_kind() -> None:
    app = ColdModelExplicitCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("**g")
            ta.cursor_location = (0, 3)

            assert ta._try_model_explicit_completion() is True

            ta._completion_kind = MODEL_ALIAS_COMPLETION_KIND
            with patch.object(ta, "_refresh_file_completion_from_cursor") as refresh:
                ta._apply_model_completion_catalog_result(
                    ModelCompletionCatalogWorkerResult(
                        rows=_model_entries(),
                        available=True,
                    )
                )

            refresh.assert_not_called()
            assert ta._model_completion_catalog_loaded is True
            assert ta._model_completion_catalog_available is True


async def test_model_catalog_worker_rejects_stale_explicit_prompt_state() -> None:
    app = ColdModelExplicitCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("**g")
            ta.cursor_location = (0, 3)

            assert ta._try_model_explicit_completion() is True

            ta.load_text("**f")
            ta.cursor_location = (0, 3)
            with patch.object(ta, "_refresh_file_completion_from_cursor") as refresh:
                ta._apply_model_completion_catalog_result(
                    ModelCompletionCatalogWorkerResult(
                        rows=_model_entries(),
                        available=True,
                    )
                )

            refresh.assert_not_called()
            assert ta._model_completion_catalog_loaded is True
            assert ta._model_completion_catalog_available is True


async def test_model_catalog_failure_can_retry_explicit_unavailable_row() -> None:
    app = ColdModelExplicitCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("**")
            ta.cursor_location = (0, 2)

            assert ta._try_model_explicit_completion() is True
            ta._apply_model_completion_catalog_result(
                ModelCompletionCatalogWorkerResult(rows=(), available=False)
            )

            assert ta._model_completion_catalog_available is False
            assert ta._file_completion_candidates[0].display == "Models unavailable"

            ta._model_completion_catalog_inflight = False
            with patch.object(
                type(ta),
                "_schedule_model_completion_catalog_load",
            ) as retry:
                assert ta._try_model_explicit_completion(force=True) is True

            retry.assert_called_once_with(force=True)
            assert ta._file_completion_candidates[0].display == "Loading models…"


def test_double_star_context_rejects_protected_regions() -> None:
    protected = [
        ("a**gp", (0, 5)),
        ("path/**gp", (0, 9)),
        (r"\**gp", (0, 5)),
        ("`**gp`", (0, 4)),
        ("```\n**gp", (1, 4)),
        ("%model:**gp", (0, 11)),
        ("{{ **gp }}", (0, 7)),
        ("{% if **gp %}", (0, 10)),
        ("---\nname: **gp\n---\nbody", (1, 10)),
        ("***gp", (0, 5)),
        ("**bold**", (0, 4)),
    ]
    for text, cursor in protected:
        assert detect_model_explicit_completion_context(text, cursor) is None
