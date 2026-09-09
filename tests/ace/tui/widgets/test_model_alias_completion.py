"""Tests for ``*alias`` prompt model completion."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from textual.app import ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets._file_completion_workers import (
    ModelCompletionCatalogWorkerResult,
)
from sase.ace.tui.widgets.model_alias_completion import (
    MODEL_ALIAS_COMPLETION_KIND,
    MODEL_ALIAS_MODE_SUBTITLE,
    build_model_alias_completion_candidates,
    detect_model_alias_completion_context,
    is_model_alias_completion_placeholder,
    plan_model_alias_completion_edit,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.model_completion import ModelCompletionEntry

from tests._xprompt_model_completion_helpers import (
    clear_model_completion_cache as clear_model_completion_cache,
)

from ._completion_helpers import CompletionTestApp


class _DefaultEntries:
    pass


_USE_DEFAULT = _DefaultEntries()


class ModelAliasCompletionTestApp(CompletionTestApp):
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
            _alias_entries() if isinstance(entries, _DefaultEntries) else entries
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


class ColdModelAliasCompletionTestApp(CompletionTestApp):
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


def _alias_entries() -> tuple[ModelCompletionEntry, ...]:
    return (
        ModelCompletionEntry(
            value="@large",
            display="@large",
            description="Large model",
            kind="user_alias",
            alias_kind="user",
            target_provider="codex",
            target_model="gpt-5",
            provenance="configured",
        ),
        ModelCompletionEntry(
            value="@small",
            display="@small",
            kind="implicit_alias",
            alias_kind="role",
            target_provider="codex",
            target_model="gpt-5-mini",
            provenance="implicit",
        ),
        ModelCompletionEntry(
            value="large-model",
            display="large-model",
            description="Concrete model",
            kind="model",
            provider="codex",
            provider_display="Codex",
            aliases=("large-model",),
        ),
    )


def _navigation_alias_entries() -> tuple[ModelCompletionEntry, ...]:
    return (
        ModelCompletionEntry(
            value="@large",
            display="@large",
            description="Large model",
            kind="user_alias",
        ),
        ModelCompletionEntry(
            value="@lark",
            display="@lark",
            description="Lark model",
            kind="user_alias",
        ),
        ModelCompletionEntry(
            value="@small",
            display="@small",
            description="Small model",
            kind="implicit_alias",
        ),
        ModelCompletionEntry(
            value="large-model",
            display="large-model",
            description="Concrete model",
            kind="model",
        ),
    )


def _candidate_insertions(text_area: PromptTextArea) -> list[str]:
    return [candidate.insertion for candidate in text_area._file_completion_candidates]


def _selected_insertion(text_area: PromptTextArea) -> str:
    return text_area._file_completion_candidates[
        text_area._file_completion_index
    ].insertion


async def test_star_alias_auto_opens_and_enter_expands_without_submit() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()

        await pilot.press("*")
        await pilot.press("l")

        panel = bar.query_one("#prompt-completion", Static)
        assert ta._file_completion_active is True
        assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
        assert panel.border_title == "model aliases"
        assert [c.insertion for c in ta._file_completion_candidates] == ["@large"]
        assert "Enter → %m:@large · Large model" in str(panel.border_subtitle)
        assert bar._subtitle_base == MODEL_ALIAS_MODE_SUBTITLE

        await pilot.press("enter")

        assert ta.text == "%m:@large "
        assert app.submitted == []
        assert ta._file_completion_active is False
        assert bar._subtitle_base == bar._mode_subtitle


@pytest.mark.parametrize(
    ("text", "cursor", "query", "token"),
    [
        ("*", (0, 1), "", "*"),
        ("Use *la", (0, 7), "la", "*la"),
        ("first\nnext *SM", (1, 8), "SM", "*SM"),
        ("  *small", (0, 8), "small", "*small"),
    ],
)
def test_star_alias_context_detects_prompt_boundaries(
    text: str,
    cursor: tuple[int, int],
    query: str,
    token: str,
) -> None:
    context = detect_model_alias_completion_context(text, cursor)

    assert context is not None
    assert context.query == query
    assert context.token == token


async def test_star_alias_ctrl_t_opens_when_auto_directive_menu_is_disabled() -> None:
    app = ModelAliasCompletionTestApp(
        settings=PromptCompletionSettings(auto_directive_menu=False),
    )
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        await pilot.press("l")
        assert ta._file_completion_active is False

        await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
        assert [c.insertion for c in ta._file_completion_candidates] == ["@large"]


async def test_star_alias_navigation_preserves_selection_while_filtering() -> None:
    app = ModelAliasCompletionTestApp(entries=_navigation_alias_entries())
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        assert _candidate_insertions(ta) == ["@large", "@lark", "@small"]

        await pilot.press("down")
        assert _selected_insertion(ta) == "@lark"

        await pilot.press("l")
        assert ta.text == "*l"
        assert _candidate_insertions(ta) == ["@large", "@lark"]
        assert _selected_insertion(ta) == "@lark"

        await pilot.press("backspace")
        assert ta.text == "*"
        assert _candidate_insertions(ta) == ["@large", "@lark", "@small"]
        assert _selected_insertion(ta) == "@lark"

        await pilot.press("z")
        assert ta.text == "*z"
        assert ta._file_completion_active is False


async def test_star_alias_ctrl_l_accepts_selection_without_submit_or_newline() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        await pilot.press("s")
        await pilot.press("ctrl+l")

        assert ta.text == "%m:@small "
        assert "\n" not in ta.text
        assert app.submitted == []
        assert ta._file_completion_active is False


async def test_star_alias_subtitle_omits_missing_description() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)

        await pilot.press("*")
        await pilot.press("s")

        panel = bar.query_one("#prompt-completion", Static)
        assert str(panel.border_subtitle) == "Enter → %m:@small"


async def test_star_alias_accept_replaces_whole_token_from_mid_token_cursor() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        ta.load_text("Use *laX later")
        ta.cursor_location = (0, len("Use *la"))

        await pilot.press("ctrl+t")
        await pilot.press("enter")

        assert ta.text == "Use %m:@large later"
        assert ta.cursor_location == (0, len("Use %m:@large "))


async def test_star_alias_accept_preserves_context_and_undo_redo() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        original = "Keep\t🙂 *laX tail\nnext"
        expanded = "Keep\t🙂 %m:@large tail\nnext"
        ta.load_text(original)
        ta.cursor_location = (0, len("Keep\t🙂 *la"))

        await pilot.press("ctrl+t")
        await pilot.press("enter")

        assert ta.text == expanded
        assert ta.cursor_location == (0, len("Keep\t🙂 %m:@large "))
        assert app.submitted == []

        await pilot.press("escape")
        await pilot.press("u")

        assert ta.text == original
        assert ta._file_completion_active is False

        await pilot.press("ctrl+r")

        assert ta.text == expanded
        assert ta._file_completion_active is False


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_replacement"),
    [
        ("Use *la", (0, 7), "Use %m:@large ", "%m:@large "),
        ("Use *la now", (0, 7), "Use %m:@large now", "%m:@large "),
        ("Use *la   now", (0, 7), "Use %m:@large   now", "%m:@large "),
        ("Use *la\tnow", (0, 7), "Use %m:@large\tnow", "%m:@large"),
        ("Use *la\nnow", (0, 7), "Use %m:@large \nnow", "%m:@large "),
        ("Explain *laX later", (0, 11), "Explain %m:@large later", "%m:@large "),
        (
            "Title\r\nUse *la\ttail",
            (1, len("Use *la")),
            "Title\r\nUse %m:@large\ttail",
            "%m:@large",
        ),
        ("🙂 *la\r\nnext", (0, 5), "🙂 %m:@large \r\nnext", "%m:@large "),
    ],
)
def test_star_alias_edit_plan_is_cursor_complete(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_replacement: str,
) -> None:
    context = detect_model_alias_completion_context(text, cursor)
    assert context is not None
    candidates = build_model_alias_completion_candidates(context, _alias_entries())
    planned = plan_model_alias_completion_edit(
        text,
        cursor,
        _alias_entries(),
        candidates[0],
    )

    assert planned is not None
    assert planned.replacement == expected_replacement
    applied = (
        f"{text[: planned.replacement_start]}"
        f"{planned.replacement}"
        f"{text[planned.replacement_end :]}"
    )
    assert applied == expected_text
    assert planned.caret_offset == planned.replacement_start + len(planned.replacement)


async def test_unknown_star_alias_stays_literal_and_can_submit() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("*")
        await pilot.press("z")

        assert ta.text == "*z"
        assert ta._file_completion_active is False

        await pilot.press("enter")

        assert app.submitted == ["*z"]


async def test_loading_model_alias_row_is_not_selectable() -> None:
    app = ModelAliasCompletionTestApp(entries=None)
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptInputBar).active_text_area()
        ta.load_text("*")
        ta.cursor_location = (0, 1)

        with patch.object(type(ta), "_schedule_model_completion_catalog_load") as load:
            assert ta._try_model_alias_completion() is True

        load.assert_called_once_with()
        assert is_model_alias_completion_placeholder(ta._file_completion_candidates[0])
        assert ta._file_completion_candidates[0].display == "Loading model aliases…"
        assert bar._subtitle_base != MODEL_ALIAS_MODE_SUBTITLE

        await pilot.press("enter")

        assert ta.text == "*"
        assert app.submitted == []
        assert ta._file_completion_active is True


async def test_cold_model_alias_catalog_shows_loading_without_blocking_keys() -> None:
    app = ColdModelAliasCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True) as run_worker:
        async with app.run_test() as pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False

            await pilot.press("*")

            assert ta._file_completion_active is True
            assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
            assert is_model_alias_completion_placeholder(
                ta._file_completion_candidates[0]
            )
            assert ta._file_completion_candidates[0].display == (
                "Loading model aliases…"
            )

            await pilot.press("x")
            await pilot.press("enter")

            assert ta.text == "*x"
            assert app.submitted == []
            assert ta._file_completion_active is True

    assert any(
        kwargs.get("group") == "prompt-model-catalog" and kwargs.get("thread") is True
        for _args, kwargs in run_worker.call_args_list
    )


async def test_model_alias_catalog_worker_refreshes_matching_request() -> None:
    app = ColdModelAliasCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("*l")
            ta.cursor_location = (0, 2)

            assert ta._try_model_alias_completion() is True

            with patch.object(ta, "_refresh_file_completion_from_cursor") as refresh:
                ta._apply_model_completion_catalog_result(
                    ModelCompletionCatalogWorkerResult(
                        rows=_alias_entries(),
                        available=True,
                    )
                )

            refresh.assert_called_once_with()


async def test_model_alias_catalog_worker_rejects_stale_prompt_state() -> None:
    app = ColdModelAliasCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("*l")
            ta.cursor_location = (0, 2)

            assert ta._try_model_alias_completion() is True

            ta.load_text("*s")
            ta.cursor_location = (0, 2)
            with patch.object(ta, "_refresh_file_completion_from_cursor") as refresh:
                ta._apply_model_completion_catalog_result(
                    ModelCompletionCatalogWorkerResult(
                        rows=_alias_entries(),
                        available=True,
                    )
                )

            refresh.assert_not_called()
            assert ta._model_completion_catalog_loaded is True
            assert ta._model_completion_catalog_available is True


async def test_model_alias_catalog_failure_can_retry_from_unavailable_row() -> None:
    app = ColdModelAliasCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_inflight = False
            ta.load_text("*")
            ta.cursor_location = (0, 1)

            assert ta._try_model_alias_completion() is True
            ta._apply_model_completion_catalog_result(
                ModelCompletionCatalogWorkerResult(rows=(), available=False)
            )

            assert ta._model_completion_catalog_available is False
            assert ta._file_completion_candidates[0].display == (
                "Model aliases unavailable"
            )

            ta._model_completion_catalog_inflight = False
            with patch.object(
                type(ta),
                "_schedule_model_completion_catalog_load",
            ) as retry:
                assert ta._try_model_alias_completion(force=True) is True

            retry.assert_called_once_with(force=True)
            assert ta._file_completion_candidates[0].display == (
                "Loading model aliases…"
            )


async def test_model_alias_catalog_cache_miss_after_loaded_reschedules() -> None:
    app = ColdModelAliasCompletionTestApp()
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test() as _pilot:
            ta = app.query_one(PromptInputBar).active_text_area()
            ta._model_completion_catalog_loaded = True
            ta._model_completion_catalog_available = True
            ta._model_completion_catalog_inflight = False
            ta.load_text("*")
            ta.cursor_location = (0, 1)

            with patch.object(
                type(ta),
                "_schedule_model_completion_catalog_load",
            ) as load:
                assert ta._try_model_alias_completion() is True

            load.assert_called_once_with()
            assert ta._file_completion_candidates[0].display == (
                "Loading model aliases…"
            )


async def test_model_alias_catalog_request_does_not_revive_inactive_stack_pane() -> (
    None
):
    app = ColdModelAliasCompletionTestApp(initial_panes=["top", "*l"])
    with patch.object(PromptTextArea, "run_worker", autospec=True):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            bottom = bar.active_text_area()
            bottom._model_completion_catalog_inflight = False

            assert bottom._try_model_alias_completion() is True
            assert bottom._model_completion_catalog_request is not None

            bar.focus_relative(-1)
            await pilot.pause()

            assert bar.active_text_area() is not bottom
            assert bottom._file_completion_active is False
            with patch.object(
                bottom,
                "_refresh_file_completion_from_cursor",
            ) as refresh:
                bottom._apply_model_completion_catalog_result(
                    ModelCompletionCatalogWorkerResult(
                        rows=_alias_entries(),
                        available=True,
                    )
                )

            refresh.assert_not_called()


def test_star_alias_context_rejects_protected_regions_and_unicode_columns() -> None:
    assert detect_model_alias_completion_context("🙂 *la", (0, 5)) is not None
    protected = [
        ("a*la", (0, 4)),
        ("path/*la", (0, 8)),
        (r"\*la", (0, 4)),
        ("`*la`", (0, 3)),
        ("```\n*la", (1, 3)),
        ("%model:*la", (0, 10)),
        ("{{ *la }}", (0, 6)),
        ("{% if *la %}", (0, 9)),
        ("---\nname: *la\n---\nbody", (1, 9)),
        ("---\nmodels:\n  - *la\n---\nbody", (2, 7)),
    ]
    for text, cursor in protected:
        assert detect_model_alias_completion_context(text, cursor) is None
