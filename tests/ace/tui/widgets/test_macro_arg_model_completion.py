"""Tests for macro model arguments sharing ``%model`` completion behavior."""

from __future__ import annotations

from sase.ace.tui.widgets._directive_completion_tokens import synthetic_directive_clause
from sase.ace.tui.widgets.directive_completion import build_directive_clause_candidates
from sase.ace.tui.widgets.macro_arg_assist import MacroAssistEntry, MacroInputHint
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.macro.model_completion import ModelCompletionEntry

from ._completion_helpers import CompletionTestApp
from ._macro_arg_completion_helpers import seed_entries


def _input_entry() -> MacroAssistEntry:
    return MacroAssistEntry(
        name="research_swarm",
        insertion="#research_swarm",
        reference_prefix="#",
        kind="macro",
        input_signature=None,
        inputs=(
            MacroInputHint(
                name="claude_model",
                type="word",
                required=True,
                default_display=None,
                position=0,
                named_type="model",
                value_role="model",
            ),
        ),
        content_preview=None,
    )


def _model_entries() -> tuple[ModelCompletionEntry, ...]:
    return (
        ModelCompletionEntry(
            value="claude/",
            display="claude/",
            description="Claude",
            kind="provider",
            provider="claude",
            provider_display="Claude",
            provider_model_count=2,
        ),
        ModelCompletionEntry(
            value="opus",
            display="opus",
            description="Claude (opus)",
            provider="claude",
            provider_display="Claude",
            aliases=("opus",),
        ),
        ModelCompletionEntry(
            value="sonnet",
            display="sonnet",
            description="Claude (sonnet)",
            provider="claude",
            provider_display="Claude",
            aliases=("sonnet",),
        ),
        ModelCompletionEntry(
            value="@large",
            display="@large",
            description="Large model alias",
            kind="implicit_alias",
            alias_kind="role",
            target_provider="claude",
            target_model="opus",
            target_effort="high",
        ),
    )


async def test_model_macro_arg_rows_match_the_shared_directive_builder(
    monkeypatch,
) -> None:
    catalog = _model_entries()
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        monkeypatch.setattr(
            ta,
            "_model_completion_catalog_state",
            lambda: ("warm", catalog),
        )
        source = "#research_swarm(claude_model=claude/"
        ta.load_text(source)
        ta.cursor_location = (0, len(source))
        seed_entries(ta, [_input_entry()])
        assert ta._try_auto_macro_arg_completion() is True

        arg_candidates = ta._file_completion_candidates
        clause = synthetic_directive_clause(
            kind="directive_argument",
            token="claude/",
            directive_name="model",
            value_role="model",
        )
        directive_candidates, _ = build_directive_clause_candidates(
            clause,
            model_entries=catalog,
        )

        assert arg_candidates == directive_candidates
        assert [row.insertion for row in arg_candidates] == [
            "claude/opus",
            "claude/sonnet",
        ]


async def test_model_macro_arg_at_aliases_and_provider_drill_down(
    monkeypatch,
) -> None:
    catalog = _model_entries()
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        monkeypatch.setattr(
            ta,
            "_model_completion_catalog_state",
            lambda: ("warm", catalog),
        )
        seed_entries(ta, [_input_entry()])

        alias_source = "#research_swarm(claude_model=@"
        ta.load_text(alias_source)
        ta.cursor_location = (0, len(alias_source))
        assert ta._try_auto_macro_arg_completion() is True
        assert ta._completion_kind == "macro_arg_model"
        assert [row.insertion for row in ta._file_completion_candidates] == ["@large"]

        provider_source = "#research_swarm(claude_model=claud"
        ta.load_text(provider_source)
        ta.cursor_location = (0, len(provider_source))
        assert ta._try_auto_macro_arg_completion() is True
        provider_index = next(
            index
            for index, row in enumerate(ta._file_completion_candidates)
            if row.insertion == "claude/"
        )
        assert ta._file_completion_candidates[provider_index].is_dir is True
        ta._file_completion_index = provider_index
        assert ta._accept_file_completion() is True

        assert ta.text == "#research_swarm(claude_model=claude/"
        assert ta._file_completion_active is True
        assert {row.insertion for row in ta._file_completion_candidates} == {
            "claude/opus",
            "claude/sonnet",
        }


async def test_model_macro_arg_effort_rows_replace_only_the_suffix(
    monkeypatch,
) -> None:
    catalog = _model_entries()
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        monkeypatch.setattr(
            ta,
            "_model_completion_catalog_state",
            lambda: ("warm", catalog),
        )
        seed_entries(ta, [_input_entry()])
        source = "#research_swarm(claude_model=claude/opus@h"
        ta.load_text(source)
        ta.cursor_location = (0, len(source))

        assert ta._try_auto_macro_arg_completion() is True
        assert ta._completion_kind == "macro_arg_model"
        assert [row.insertion for row in ta._file_completion_candidates] == ["high"]
        assert ta._accept_file_completion() is True
        assert ta.text == "#research_swarm(claude_model=claude/opus@high"
