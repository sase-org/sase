"""Contextual title/subtitle tests for the ``%model`` completion panel."""

from __future__ import annotations

from textual.widgets import Static

from sase.ace.tui.widgets.directive_completion import ModelCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from .widgets._completion_helpers import CompletionTestApp


def _candidate(
    value: str,
    *,
    kind: str,
    alias_kind: str = "",
    description: str = "",
) -> CompletionCandidate:
    is_model = kind == "model"
    is_provider = kind == "provider"
    return CompletionCandidate(
        display=value,
        insertion=value,
        is_dir=is_provider,
        name=value,
        metadata=ModelCompletionMetadata(
            value=value,
            kind=kind,
            alias_kind=alias_kind,
            provider="claude" if is_model or is_provider else "",
            provider_display="Claude" if is_model or is_provider else "",
            short_alias="opus" if is_model else "",
            target_provider="" if is_model else "claude",
            target_model="" if is_model else "opus",
            provenance="" if is_model else "configured",
            description=description,
            config_source="custom" if alias_kind == "user" else "",
            provider_model_count=2 if is_provider else 0,
        ),
    )


async def test_model_completion_panel_teaches_alias_gate_for_model_row() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)
        rows = [
            _candidate("claude-fable-5", kind="model"),
            _candidate(
                "@default",
                kind="implicit_alias",
                alias_kind="default",
                description="Default launch model.",
            ),
        ]

        bar.show_file_completions(
            "",
            rows,
            selected_index=0,
            completion_kind="directive_arg",
        )

        assert panel.border_title == "%model values"
        assert panel.border_subtitle.replace(r"\[", "[") == "[@] model aliases"


async def test_alias_only_panel_uses_selected_alias_description() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)
        rows = [
            _candidate(
                "@default",
                kind="implicit_alias",
                alias_kind="default",
                description="Default launch model.",
            )
        ]

        bar.show_file_completions(
            "@",
            rows,
            selected_index=0,
            completion_kind="directive_arg",
        )

        assert panel.border_title == "model aliases"
        assert panel.border_subtitle == "Default launch model."


async def test_custom_alias_without_description_shows_config_hint() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)
        rows = [
            _candidate(
                "@scout",
                kind="user_alias",
                alias_kind="user",
            )
        ]

        bar.show_file_completions(
            "@sc",
            rows,
            selected_index=0,
            completion_kind="directive_arg",
        )

        assert panel.border_title == "model aliases"
        assert panel.border_subtitle == (
            "set llm_provider.model_aliases.custom.scout.description"
        )


async def test_provider_scoped_model_panel_uses_provider_title() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)
        rows = [_candidate("claude/opus", kind="model")]

        bar.show_file_completions(
            "claude/",
            rows,
            selected_index=0,
            completion_kind="directive_arg",
        )

        assert panel.border_title == "claude/ models"
        assert panel.border_subtitle.replace(r"\[", "[") == "[@] model aliases"


async def test_provider_completion_row_subtitle_explains_drill_down() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)
        rows = [_candidate("claude/", kind="provider", description="Claude")]

        bar.show_file_completions(
            "cl",
            rows,
            selected_index=0,
            completion_kind="directive_arg",
        )

        assert panel.border_title == "%model values"
        assert panel.border_subtitle == "[Enter] show Claude models"
