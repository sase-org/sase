"""Ctrl+T yields ``auto``-typed next-word chains to manual completion.

Regression tests for the typed-chain yield: with the default
``next_word="auto"`` mode, typing arms a chain after almost every keystroke,
so an armed chain alone is not a request. ``Ctrl+T`` must fall through to
the manual dispatcher (structured tokens, paths, prompt-local and history
words) unless a ghost is visible or a peek waits for the reveal beat.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.pilot import Pilot

from sase.ace.tui.widgets.next_word_completion import (
    NEXT_WORD_NO_GUESS_HINT,
    NEXT_WORD_NO_GUESS_RECENT_FILES_HINT,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.core.prompt_prediction_wire import PromptPredictionResult

from ._history_word_completion_helpers import (
    HistoryCompletionTestApp,
    skip_unrelated_vcs_catalog_warm,  # noqa: F401 (registers the autouse fixture)
)
from .test_prompt_next_word import NextWordTestApp, _bar_hint

_KEY_BY_CHAR = {
    " ": "space",
    "+": "plus",
    "-": "minus",
    "/": "slash",
    ":": "colon",
    "#": "number_sign",
    "=": "equals_sign",
    ".": "full_stop",
}


async def _type(pilot: Pilot, text: str) -> None:
    """Type *text* keystroke by keystroke so ``auto`` triggers arm."""
    await pilot.press(*[_KEY_BY_CHAR.get(char, char) for char in text])


def _unconfident_result() -> PromptPredictionResult:
    """A warm-model miss: no confident guess and no candidates."""
    return PromptPredictionResult(
        schema_version=1,
        blocked_reason=None,
        context_words=["help", "me"],
        confident=False,
        ghost=[],
        candidates=[],
    )


def _recent_settings() -> PromptCompletionSettings:
    """Default ``auto`` next-word mode with recent history-word ranking."""
    return PromptCompletionSettings(word_ranking="recent")


async def test_typed_chain_yields_ctrl_t_to_history_word_cold() -> None:
    """Cold-model typed chain still completes the history word."""
    app = HistoryCompletionTestApp(["bob-mac-capture"], settings=_recent_settings())
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _type(pilot, "+bob-cli bob-m")
        assert ta.text == "+bob-cli bob-m"
        assert ta._file_completion_active is False
        assert ta._next_word_chain is not None
        assert ta._next_word_chain.typed is True
        assert ta._next_word_chain.midword is True
        assert ta._next_word_chain_is_armed() is True

        await pilot.press("ctrl+t")

        assert ta.text == "+bob-cli bob-mac-capture"
        assert ta._file_completion_active is False


async def test_typed_chain_yields_ctrl_t_to_history_word_no_guess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warm-model miss on the typed chain still completes the history word."""
    app = HistoryCompletionTestApp(["bob-mac-capture"], settings=_recent_settings())
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        monkeypatch.setattr(
            ta, "_predict_next_words", lambda *args, **kwargs: _unconfident_result()
        )
        await _type(pilot, "+bob-cli bob-m")
        assert ta.text == "+bob-cli bob-m"
        assert ta._next_word_chain is not None
        assert ta._next_word_chain.typed is True
        assert ta._next_word_chain.midword is True
        assert ta._next_word_chain_is_armed() is True

        await pilot.press("ctrl+t")

        assert ta.text == "+bob-cli bob-mac-capture"
        assert ta._file_completion_active is False


async def test_typed_chain_yields_ctrl_t_to_path_mid_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typed mid-token chain completes the lone path match."""
    srcdir = tmp_path / "srcdir"
    srcdir.mkdir()
    (srcdir / "alpha.py").write_text("x", encoding="utf-8")
    (srcdir / "beta.py").write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    app = HistoryCompletionTestApp([], settings=_recent_settings())
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _type(pilot, "see srcdir/al")
        assert ta.text == "see srcdir/al"
        assert ta._file_completion_active is False
        assert ta._next_word_chain is not None
        assert ta._next_word_chain.typed is True
        assert ta._next_word_chain.midword is True
        assert ta._next_word_chain_is_armed() is True

        await pilot.press("ctrl+t")

        assert ta.text == "see srcdir/alpha.py"


async def test_typed_boundary_chain_yields_ctrl_t_to_path_menu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typed separator chain opens the file menu instead of hinting."""
    srcdir = tmp_path / "srcdir"
    srcdir.mkdir()
    (srcdir / "alpha.py").write_text("x", encoding="utf-8")
    (srcdir / "beta.py").write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    app = HistoryCompletionTestApp([], settings=_recent_settings())
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _type(pilot, "see srcdir/")
        assert ta.text == "see srcdir/"
        assert ta._file_completion_active is False
        assert ta._next_word_chain is not None
        assert ta._next_word_chain.typed is True
        assert ta._next_word_chain.midword is False
        assert ta._next_word_chain_is_armed() is True

        await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == "file"


async def test_typed_boundary_yields_then_requests_next_words() -> None:
    """A guess-free boundary still teaches ``Ctrl+G r`` via row 4."""
    app = NextWordTestApp(settings=PromptCompletionSettings(next_word="auto"))
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        await _type(pilot, "zzz qqq ")
        assert ta.text == "zzz qqq "
        assert ta._next_word_chain is not None
        assert ta._next_word_chain.typed is True
        assert ta._next_word_chain_is_armed() is True

        await pilot.press("ctrl+t")

        assert ta._file_completion_active is False
        assert NEXT_WORD_NO_GUESS_RECENT_FILES_HINT in _bar_hint(bar)


async def test_typed_word_end_miss_falls_back_to_next_words() -> None:
    """A word end with no completion candidate requests next words."""
    app = NextWordTestApp(settings=PromptCompletionSettings(next_word="auto"))
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        await _type(pilot, "zzz qqq")
        assert ta.text == "zzz qqq"
        assert ta._next_word_chain is not None
        assert ta._next_word_chain.typed is True
        assert ta._next_word_chain_is_armed() is True

        await pilot.press("ctrl+t")

        assert ta._file_completion_active is False
        hint = _bar_hint(bar)
        assert NEXT_WORD_NO_GUESS_HINT in hint
        assert NEXT_WORD_NO_GUESS_RECENT_FILES_HINT not in hint
