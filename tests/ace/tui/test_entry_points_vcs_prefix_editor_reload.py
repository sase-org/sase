"""Tests for editor reload behavior in VCS-prefixed entry points."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._entry_points_vcs_prefix_helpers import (
    _EDIT_MULTI_AGENT_MARKDOWN,
    _EditorApp,
    _LIFTED_FRONTMATTER,
)


def test_select_and_open_editor_for_home_edit_directive_reloads_as_review() -> None:
    """A ``%edit`` multi-agent markdown editor return mounts a review bar.

    ``_select_and_open_editor_for_home`` strips ``%edit``, mounts a prompt bar
    with editor-file (xprompt markdown) semantics - lifting frontmatter and
    splitting ``---`` into panes - never launches, and preserves the caller's
    display/history context rather than falling back to generic home labels.
    """
    app = _EditorApp(editor_result=_EDIT_MULTI_AGENT_MARKDOWN)

    app._select_and_open_editor_for_home(
        initial_text="#gh:sase ",
        display_name="sase",
        history_sort_key="sase",
    )

    # The agent is not launched; a single review bar is mounted instead.
    assert app.finished_prompts == []
    assert len(app.mounted) == 1
    bar = app.mounted[0]
    assert isinstance(bar, PromptInputBar)

    # Editor-file semantics: leading frontmatter is lifted and the body splits.
    assert len(bar._stack) == 2
    assert bar._stack.texts == ["Review auth.", "Review API."]
    assert bar._stack.frontmatter == _LIFTED_FRONTMATTER

    # The caller's launch context is preserved on the review bar's context.
    assert app._prompt_context is not None
    assert app._prompt_context.display_name == "sase"
    assert app._prompt_context.history_sort_key == "sase"
