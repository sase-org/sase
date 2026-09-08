"""Tests for ``*alias`` prompt model completion."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.widgets.model_alias_completion import (
    MODEL_ALIAS_COMPLETION_KIND,
    MODEL_ALIAS_MODE_SUBTITLE,
    detect_model_alias_completion_context,
    is_model_alias_completion_placeholder,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.model_completion import ModelCompletionEntry

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
    ) -> None:
        super().__init__()
        self.entries: tuple[ModelCompletionEntry, ...] | None = (
            _alias_entries() if isinstance(entries, _DefaultEntries) else entries
        )
        self.settings = settings or PromptCompletionSettings()
        self.available = available
        self.submitted: list[str] = []

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
            aliases=("large-model",),
        ),
    )


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
        assert "Enter -> %m:@large" in str(panel.border_subtitle)
        assert bar._subtitle_base == MODEL_ALIAS_MODE_SUBTITLE

        await pilot.press("enter")

        assert ta.text == "%m:@large "
        assert app.submitted == []
        assert ta._file_completion_active is False
        assert bar._subtitle_base == bar._mode_subtitle


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
        ta = app.query_one(PromptInputBar).active_text_area()
        ta.load_text("*")
        ta.cursor_location = (0, 1)

        with patch.object(type(ta), "_schedule_model_completion_catalog_load") as load:
            assert ta._try_model_alias_completion() is True

        load.assert_called_once_with()
        assert is_model_alias_completion_placeholder(ta._file_completion_candidates[0])

        await pilot.press("enter")

        assert ta.text == "*"
        assert app.submitted == []
        assert ta._file_completion_active is True


def test_star_alias_context_rejects_protected_regions_and_unicode_columns() -> None:
    assert detect_model_alias_completion_context("🙂 *la", (0, 5)) is not None
    protected = [
        ("a*la", (0, 4)),
        ("path/*la", (0, 8)),
        (r"\*la", (0, 4)),
        ("`*la`", (0, 3)),
        ("%model:*la", (0, 10)),
        ("---\nname: *la\n---\nbody", (1, 9)),
    ]
    for text, cursor in protected:
        assert detect_model_alias_completion_context(text, cursor) is None
