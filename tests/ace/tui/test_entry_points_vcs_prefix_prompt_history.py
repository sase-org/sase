"""Tests for prompt-history VCS prefix entry points."""

from __future__ import annotations

import pytest

from sase.history.prompt_catalog import record_from_entry
from sase.history.prompt_store import PromptEntry

from ._entry_points_vcs_prefix_helpers import (
    _App,
    _CLEANED_MULTI_AGENT_MARKDOWN,
    _MARKED_MULTI_AGENT_MARKDOWN,
)


def _patch_mru_pairs(
    monkeypatch: pytest.MonkeyPatch, pairs: list[tuple[str, str]]
) -> None:
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru_pairs",
        lambda *a, **k: pairs,
    )


def test_prompt_history_edit_first_uses_first_non_cancelled_modal_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_mru_pairs(monkeypatch, [("#gh:target", "#gh:target")])
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

    app._start_prompt_history_from_last_selection(edit_first=True)

    assert app.editor_prompts == ["#gh:target picked prompt"]
    assert app.finished_prompts == ["edited: #gh:target picked prompt"]
    assert app.notifications == []
    assert app._prompt_context is not None
    assert app._prompt_context.history_sort_key == "target"


def test_prompt_history_project_selection_uses_configured_name_in_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured ``PROJECT_NAME`` humanizes the bar label and prefix.

    The history grouping key stays the canonical directory key.
    """
    _patch_mru_pairs(monkeypatch, [("#gh:gh_acme__widgets", "#gh:widgets")])
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

    app._start_prompt_history_from_last_selection(edit_first=True)

    assert app.editor_prompts == ["#gh:widgets picked prompt"]
    assert app.finished_prompts == ["edited: #gh:widgets picked prompt"]
    assert app._prompt_context is not None
    assert app._prompt_context.display_name == "widgets"
    assert app._prompt_context.history_sort_key == "gh_acme__widgets"


def test_prompt_history_edit_first_notifies_when_no_non_cancelled_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_mru_pairs(monkeypatch, [("#gh:target", "#gh:target")])
    monkeypatch.setattr(
        "sase.history.prompt.list_prompt_records",
        lambda *, limit: [],
    )
    app = _App()

    app._start_prompt_history_from_last_selection(edit_first=True)

    assert app.editor_prompts == []
    assert app.finished_prompts == []
    assert app.notifications == [("No prompt history entry to edit", "warning")]
    assert app._prompt_context is None


def test_prompt_history_warns_when_mru_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same empty-MRU warning text as ``<ctrl+space>``."""
    _patch_mru_pairs(monkeypatch, [])
    app = _App()

    app._start_prompt_history_from_last_selection(edit_first=True)

    assert app.editor_prompts == []
    assert app.finished_prompts == []
    assert app.notifications == [("No previously launched VCS xprompt", "warning")]
    assert app._prompt_context is None


def test_prompt_history_edit_first_review_marker_reloads_instead_of_launching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edit-first ` @` review marker reloads the bar instead of launching.

    The prompt-history-last-selection edit path honors the ` @` review marker
    like the other editor returns: the cleaned multi-agent markdown is mounted
    for review with the selection's context and editor-file semantics, and no
    agent launches.
    """
    _patch_mru_pairs(monkeypatch, [("#gh:target", "#gh:target")])
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

    class _AppReviewMarker(_App):
        def _open_editor_for_agent_prompt(self, prompt: str) -> str:
            self.editor_prompts.append(prompt)
            return _MARKED_MULTI_AGENT_MARKDOWN

    app = _AppReviewMarker()

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
