"""Tests for prompt-history VCS prefix entry points."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agent_workflow import _entry_points
from sase.ace.tui.modals import SelectionItem
from sase.history.prompt_catalog import record_from_entry
from sase.history.prompt_store import PromptEntry

from ._entry_points_vcs_prefix_helpers import (
    _App,
    _CLEANED_MULTI_AGENT_MARKDOWN,
    _EDIT_MULTI_AGENT_MARKDOWN,
)


def test_prompt_history_edit_first_uses_first_non_cancelled_modal_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.history.prompt.list_prompt_records",
        lambda *, limit: [
            record_from_entry(
                PromptEntry(
                    text="picked prompt",
                    branch_or_workspace="target",
                    timestamp="260509_090000",
                    last_used="260509_120000",
                    workspace="home",
                )
            )
        ],
    )
    app = _App()
    app._last_custom_agent_selection = SelectionItem(
        display_name="Target",
        item_type="cl",
        project_name="proj",
        cl_name="target",
    )

    app._start_prompt_history_from_last_selection(edit_first=True)

    assert app.editor_prompts == ["#gh:target picked prompt"]
    assert app.finished_prompts == ["edited: #gh:target picked prompt"]
    assert app.notifications == []
    assert app._prompt_context is not None
    assert app._prompt_context.history_sort_key == "target"


def test_prompt_history_edit_first_notifies_when_no_non_cancelled_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.history.prompt.list_prompt_records",
        lambda *, limit: [],
    )
    app = _App()
    app._last_custom_agent_selection = SelectionItem(
        display_name="Target",
        item_type="cl",
        project_name="proj",
        cl_name="target",
    )

    app._start_prompt_history_from_last_selection(edit_first=True)

    assert app.editor_prompts == []
    assert app.finished_prompts == []
    assert app.notifications == [("No prompt history entry to edit", "warning")]
    assert app._prompt_context is None


def test_prompt_history_edit_first_edit_directive_reloads_instead_of_launching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edit-first ``%edit`` reloads the bar for review instead of launching.

    The prompt-history-last-selection edit path honors ``%edit`` like the other
    editor returns: the cleaned multi-agent markdown is mounted for review with
    the selection's context and editor-file semantics, and no agent launches.
    """
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.history.prompt.list_prompt_records",
        lambda *, limit: [
            record_from_entry(
                PromptEntry(
                    text="picked prompt",
                    branch_or_workspace="target",
                    timestamp="260509_090000",
                    last_used="260509_120000",
                    workspace="home",
                )
            )
        ],
    )

    class _AppEditDirective(_App):
        def _open_editor_for_agent_prompt(self, prompt: str) -> str:
            self.editor_prompts.append(prompt)
            return _EDIT_MULTI_AGENT_MARKDOWN

    app = _AppEditDirective()
    app._last_custom_agent_selection = SelectionItem(
        display_name="Target",
        item_type="cl",
        project_name="proj",
        cl_name="target",
    )

    app._start_prompt_history_from_last_selection(edit_first=True)

    # The editor opened on the resolved history entry, but nothing launched.
    assert app.editor_prompts == ["#gh:target picked prompt"]
    assert app.finished_prompts == []

    # Instead, a review bar is mounted with editor-file semantics + context.
    assert app.prompt_launches == [
        {
            "initial_text": _CLEANED_MULTI_AGENT_MARKDOWN,
            "display_name": "target",
            "history_sort_key": "target",
            "as_xprompt_markdown": True,
        }
    ]
