"""Tests for MRU VCS xprompt entry points."""

from __future__ import annotations

import pytest

from ._entry_points_vcs_prefix_helpers import (
    _App,
    _EditorApp,
    _patch_tag_peek,
    _tag_catalog,
)


def test_start_last_vcs_xprompt_editor_opens_mru_prefix_and_launches_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru_pairs",
        lambda *a, **k: [("#gh:sase", "#gh:sase"), ("#gh:old", "#gh:old")],
    )
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _EditorApp()

    app.action_start_last_vcs_xprompt_in_editor()

    assert app.editor_prompts == ["+sase "]
    assert app.finished_prompts == ["edited: +sase "]
    assert app.notifications == []
    assert app._prompt_context is not None
    assert app._prompt_context.display_name == "sase"
    assert app._prompt_context.history_sort_key == "sase"


def test_start_last_vcs_xprompt_editor_uses_canonical_history_sort_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The editor's history grouping key uses the canonical ref, not the display one.

    Regression test for Defect 4: a project whose configured display name
    differs from its on-disk directory key must group prompt history under
    the canonical key, matching every other prefill surface.
    """
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru_pairs",
        lambda *a, **k: [("#gh:gh_acme__widgets", "#gh:widgets")],
    )
    _patch_tag_peek(monkeypatch, _tag_catalog("widgets"))
    app = _EditorApp()

    app.action_start_last_vcs_xprompt_in_editor()

    assert app.editor_prompts == ["+widgets "]
    assert app._prompt_context is not None
    assert app._prompt_context.display_name == "widgets"
    assert app._prompt_context.history_sort_key == "gh_acme__widgets"


def test_start_last_vcs_xprompt_editor_labels_tagified_display_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tagified ``+sase`` display prefix labels the bar ``sase``.

    Regression test for the display-fixes MRU label bug: the ``#``-only
    extractor returned ``None`` for tags, so the bar label showed
    ``+sase`` instead of ``sase``.
    """
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru_pairs",
        lambda *a, **k: [("#gh:sase", "+sase ")],
    )
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _EditorApp()

    app.action_start_last_vcs_xprompt_in_editor()

    assert app.editor_prompts == ["+sase "]
    assert app._prompt_context is not None
    assert app._prompt_context.display_name == "sase"
    assert app._prompt_context.history_sort_key == "sase"


def test_start_last_vcs_xprompt_editor_warns_when_mru_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru_pairs",
        lambda *a, **k: [],
    )
    app = _App()

    app.action_start_last_vcs_xprompt_in_editor()

    assert app.editor_launches == []
    assert app.prompt_launches == []
    assert app.notifications == [("No previous VCS xprompt", "warning")]


def test_start_last_vcs_xprompt_editor_cancel_records_prefilled_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled_prompts: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru_pairs",
        lambda *a, **k: [("#gh:sase", "#gh:sase")],
    )

    def _record_cancelled_prompt(text: str, *, cancelled: bool = False) -> None:
        cancelled_prompts.append((text, cancelled))

    monkeypatch.setattr(
        "sase.history.prompt.add_or_update_prompt",
        _record_cancelled_prompt,
    )
    _patch_tag_peek(monkeypatch, _tag_catalog("sase"))
    app = _EditorApp(editor_result="")

    app.action_start_last_vcs_xprompt_in_editor()

    assert app.editor_prompts == ["+sase "]
    assert cancelled_prompts == [("+sase", True)]
    assert app.notifications == [("No prompt from editor - cancelled", "warning")]
    assert app._prompt_context is None
