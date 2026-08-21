"""ACE ``%final`` argument completion against the shared Rust candidate builder."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.directive_completion import (
    DirectiveCatalogPlaceholder,
    FinalizerCompletionMetadata,
    build_directive_clause_candidates,
    classify_directive_completion,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from textual.widgets import Static

from ._completion_helpers import CompletionTestApp

SAMPLE_FINALIZERS = (
    {
        "value": "commit",
        "display": "commit",
        "provider_ref": "builtin@commit",
        "detail": "builtin@commit",
        "required": True,
        "default": True,
        "max_attempts": 2,
        "documentation": "Required for this launch.",
    },
    {
        "value": "lint",
        "display": "lint",
        "provider_ref": "builtin@command",
        "detail": "builtin@command",
        "default": True,
        "after": ["format"],
        "max_attempts": 2,
        "documentation": "Selected by default.",
    },
    {
        "value": "zoom",
        "display": "zoom",
        "provider_ref": "plugin@zoom",
        "detail": "plugin@zoom",
        "max_attempts": 1,
        "documentation": "Optional.",
    },
)


def _clause(line: str, cursor: int | None = None):
    clause = classify_directive_completion(
        line, len(line) if cursor is None else cursor
    )
    assert clause is not None
    return clause


def test_finalizer_add_rows_use_core_policy_order() -> None:
    candidates, _ = build_directive_clause_candidates(
        _clause("%final:"),
        finalizer_inventory=SAMPLE_FINALIZERS,
        finalizers_state="warm",
    )

    assert [candidate.insertion for candidate in candidates] == [
        "commit",
        "lint",
        "zoom",
    ]
    metadata = candidates[0].metadata
    assert isinstance(metadata, FinalizerCompletionMetadata)
    assert metadata.state_label == "required"
    assert metadata.provider == "builtin@commit"


def test_colon_bang_is_a_finalizer_remove_clause() -> None:
    clause = _clause("%final:!")
    assert clause.directive_name == "final"
    assert clause.token == "!"
    assert clause.value_role == "finalizer_instance"


def test_finalizer_remove_omits_required_and_clear() -> None:
    candidates, _ = build_directive_clause_candidates(
        _clause("%final:!"),
        finalizer_inventory=SAMPLE_FINALIZERS,
        finalizers_state="warm",
    )

    assert [candidate.insertion for candidate in candidates] == ["!lint", "!zoom"]
    assert all(
        isinstance(candidate.metadata, FinalizerCompletionMetadata)
        and candidate.metadata.state_label == "remove"
        for candidate in candidates
    )


def test_none_is_absent_when_any_finalizer_is_required() -> None:
    required_only = (SAMPLE_FINALIZERS[0],)
    candidates, _ = build_directive_clause_candidates(
        _clause("%final:n"),
        finalizer_inventory=required_only,
        finalizers_state="warm",
    )

    assert [candidate.insertion for candidate in candidates] == []


def test_none_is_offered_when_catalog_has_no_required_instances() -> None:
    optional = (SAMPLE_FINALIZERS[2],)
    candidates, _ = build_directive_clause_candidates(
        _clause("%final:n"),
        finalizer_inventory=optional,
        finalizers_state="warm",
    )

    assert [candidate.insertion for candidate in candidates] == ["none"]


def test_finalizer_loading_and_unavailable_use_nonselectable_placeholders() -> None:
    loading, _ = build_directive_clause_candidates(
        _clause("%final:"),
        finalizers_state="loading",
    )
    unavailable, _ = build_directive_clause_candidates(
        _clause("%final:"),
        finalizers_state="unavailable",
    )

    assert len(loading) == 1
    assert isinstance(loading[0].metadata, DirectiveCatalogPlaceholder)
    assert loading[0].metadata.kind == "loading"
    assert loading[0].metadata.catalog == "finalizers"
    assert loading[0].insertion == ""
    assert isinstance(unavailable[0].metadata, DirectiveCatalogPlaceholder)
    assert unavailable[0].metadata.kind == "unavailable"


def test_parenthesized_finalizer_clause_replaces_only_the_active_fragment() -> None:
    line = "%final(commit, !l"
    clause = _clause(line)
    candidates, _ = build_directive_clause_candidates(
        clause,
        finalizer_inventory=SAMPLE_FINALIZERS,
        finalizers_state="warm",
    )

    assert clause.token == "!l"
    assert [candidate.insertion for candidate in candidates] == ["!lint"]


def test_colon_prefix_filters_case_insensitively() -> None:
    candidates, _ = build_directive_clause_candidates(
        _clause("%final:L"),
        finalizer_inventory=SAMPLE_FINALIZERS,
        finalizers_state="warm",
    )

    assert [candidate.insertion for candidate in candidates] == ["lint"]


async def test_finalizer_menu_uses_warm_inventory_without_loading_config() -> None:
    app = CompletionTestApp()
    app.finalizer_inventory = lambda: (SAMPLE_FINALIZERS, True)  # type: ignore[attr-defined]
    with patch("sase.finalizers.catalog.load_finalizer_config") as loader:
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            for char in "%final:":
                await pilot.press(char)

            assert ta._completion_kind == "directive_arg"
            assert [
                candidate.insertion for candidate in ta._file_completion_candidates
            ] == ["commit", "lint", "zoom"]
            bar = app.query_one(PromptInputBar)
            panel = bar.query_one("#prompt-completion", Static)
            assert panel.border_title == "%final values"
            assert "required" in panel.render().plain

    loader.assert_not_called()


async def test_finalizer_tab_replaces_only_active_parenthesized_clause() -> None:
    app = CompletionTestApp()
    app.finalizer_inventory = lambda: (SAMPLE_FINALIZERS, True)  # type: ignore[attr-defined]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%final(commit, li")
        ta.cursor_location = (0, len("%final(commit, li"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%final(commit, lint"


async def test_finalizer_remove_tab_inserts_bang_prefix() -> None:
    app = CompletionTestApp()
    app.finalizer_inventory = lambda: (SAMPLE_FINALIZERS, True)  # type: ignore[attr-defined]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%final:!")
        ta.cursor_location = (0, len("%final:!"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == [
            "!lint",
            "!zoom",
        ]
        ta._file_completion_index = 0
        assert ta._accept_file_completion() is True

    assert ta.text.startswith("%final:!lint")
