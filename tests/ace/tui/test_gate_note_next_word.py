"""Pilot tests for next-word autosuggest in the gate note editor."""

from __future__ import annotations

import time
from typing import Any

from textual.app import App

from sase.ace.tui.modals.gate_input_panel import GateInputPanel
from sase.ace.tui.modals.gate_input_panel_model import (
    GateInputDraft,
    build_gate_input_request,
)
from sase.ace.tui.modals.gate_input_panel_note import GateNoteInput
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.core.prompt_prediction_facade import (
    PromptPredictionCorpus,
    PromptPredictionModel,
)
from sase.core.prompt_prediction_wire import (
    PromptPredictionCorpusOptions,
    PromptPredictionRow,
)
from sase.notification_gates.models import GateOption


def _corpus_texts() -> list[str]:
    return [
        "Can you help me implement it now",
        "Can you help me implement it today",
        "Can you help me implement it soon",
        "Can you help me implement it later",
        "Can you help me implement it quickly",
        "Can you help me implement it cleanly",
        "Can you help me implement it safely",
        "Can you help me implement it tomorrow",
    ]


def _compile_model() -> PromptPredictionModel:
    from sase.core.prompt_prediction_wire import PromptPredictionModelConfig

    now = int(time.time())
    rows = [
        PromptPredictionRow(text=text, epoch_seconds=now - index * 100, origin="typed")
        for index, text in enumerate(_corpus_texts())
    ]
    corpus = PromptPredictionCorpus.compile(
        rows, PromptPredictionCorpusOptions(now_epoch=now)
    )
    return PromptPredictionModel.compose(
        [(corpus, "history", 1.0)], PromptPredictionModelConfig()
    )


class GateNoteTestApp(App[None]):
    """Minimal app hosting the gate panel with a warm prediction model."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        *,
        settings: PromptCompletionSettings | None = None,
        model: PromptPredictionModel | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings or PromptCompletionSettings()
        self.model = model if model is not None else _compile_model()
        self.warm_requests = 0
        self.disabled = False
        self.results: list[Any] = []

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings

    def get_prompt_prediction_model(self) -> PromptPredictionModel | None:
        return None if self.disabled else self.model

    def get_prompt_prediction_project(self, _text: str) -> str | None:
        return None

    def prompt_prediction_disabled(self) -> bool:
        return self.disabled

    def disable_prompt_prediction(self) -> None:
        self.disabled = True

    def warm_prompt_prediction(self) -> None:
        self.warm_requests += 1

    def history_prompt_word_deletions(self) -> frozenset[str]:
        return frozenset()


def _note_option() -> GateOption:
    return GateOption.from_mapping(
        {
            "id": "accept",
            "label": "Accept",
            "command": {"argv": ["commands/accept"]},
            "feedback": "required",
        },
        0,
    )


def _note_request(feedback_mode: str = "required"):
    option = _note_option()
    return build_gate_input_request(
        (option,),
        ("accept",),
        branch_index=0,
        branch_label="Accept",
        feedback_mode=feedback_mode,  # type: ignore[arg-type]
        draft=GateInputDraft(),
    )


def _note_hint(note: GateNoteInput) -> str:
    subtitle = note.border_subtitle
    return subtitle.plain if hasattr(subtitle, "plain") else str(subtitle)


async def test_gate_note_explicit_ctrl_t_shows_ghost() -> None:
    app = GateNoteTestApp()
    panel = GateInputPanel(_note_request())
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        note = panel.query_one("#gate-input-note", GateNoteInput)
        note.focus()
        await pilot.pause()
        note.text = "Can you help me"
        note.cursor_location = (0, len(note.text))
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert note._next_word_ghost_visible() is True
        assert note.suggestion == " implement it"
        assert "[^T] word" in _note_hint(note)


async def test_gate_note_ctrl_t_takes_one_word() -> None:
    app = GateNoteTestApp()
    panel = GateInputPanel(_note_request())
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        note = panel.query_one("#gate-input-note", GateNoteInput)
        note.focus()
        await pilot.pause()
        note.text = "Can you help me"
        note.cursor_location = (0, len(note.text))
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        before = note.text
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert note.text.startswith(before + " implement")
        assert note._next_word_chain_is_armed() is True


async def test_gate_note_ctrl_l_takes_all() -> None:
    app = GateNoteTestApp()
    panel = GateInputPanel(_note_request())
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        note = panel.query_one("#gate-input-note", GateNoteInput)
        note.focus()
        await pilot.pause()
        note.text = "Can you help me"
        note.cursor_location = (0, len(note.text))
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        ghost = note.suggestion
        assert ghost
        before = note.text
        await pilot.press("ctrl+l")
        await pilot.pause()
        assert note.text == before + ghost


async def test_gate_note_mid_sentence_shows_peek() -> None:
    app = GateNoteTestApp()
    panel = GateInputPanel(_note_request())
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        note = panel.query_one("#gate-input-note", GateNoteInput)
        note.focus()
        await pilot.pause()
        note.text = "Can you help me here"
        note.cursor_location = (0, len("Can you help me"))
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert note._next_word_ghost_visible() is False
        assert note._next_word_peek_visible() is True


async def test_gate_note_no_guess_shows_hint_not_menu() -> None:
    app = GateNoteTestApp()
    panel = GateInputPanel(_note_request())
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        note = panel.query_one("#gate-input-note", GateNoteInput)
        note.focus()
        await pilot.pause()
        note.text = "zzz qqq"
        note.cursor_location = (0, len(note.text))
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert note._next_word_ghost_visible() is False
        assert note._next_word_peek_visible() is False
        assert "no next-word guess" in _note_hint(note)


async def test_gate_note_cursor_move_clears_ghost() -> None:
    app = GateNoteTestApp()
    panel = GateInputPanel(_note_request())
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        note = panel.query_one("#gate-input-note", GateNoteInput)
        note.focus()
        await pilot.pause()
        note.text = "Can you help me"
        note.cursor_location = (0, len(note.text))
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert note._next_word_ghost_visible() is True
        await pilot.press("left")
        await pilot.pause()
        assert note._next_word_ghost_visible() is False
        assert note.suggestion == ""


async def test_gate_note_off_shows_nothing() -> None:
    settings = PromptCompletionSettings(next_word="off")
    app = GateNoteTestApp(settings=settings)
    panel = GateInputPanel(_note_request())
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        note = panel.query_one("#gate-input-note", GateNoteInput)
        note.focus()
        await pilot.pause()
        note.text = "Can you help me"
        note.cursor_location = (0, len(note.text))
        await pilot.pause()
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert note._next_word_ghost_visible() is False
        assert note._next_word_peek_visible() is False
        assert note._predict_next_words("Can you help me") is None


async def test_gate_note_chain_mode_ignores_typing() -> None:
    app = GateNoteTestApp(settings=PromptCompletionSettings(next_word="chain"))
    panel = GateInputPanel(_note_request())
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        note = panel.query_one("#gate-input-note", GateNoteInput)
        note.focus()
        await pilot.pause()
        note.text = "Can you help me,"
        note.cursor_location = (0, len(note.text))
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert note.text == "Can you help me, "
        assert note._next_word_ghost_visible() is False


async def test_gate_note_auto_mode_suggests_after_space() -> None:
    settings = PromptCompletionSettings(next_word="auto")
    app = GateNoteTestApp(settings=settings)
    panel = GateInputPanel(_note_request())
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        note = panel.query_one("#gate-input-note", GateNoteInput)
        note.focus()
        await pilot.pause()
        note.text = "Can you help me,"
        note.cursor_location = (0, len(note.text))
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert note.text == "Can you help me, "
        assert note._next_word_ghost_visible() is True


async def test_gate_note_typing_through_ghost_reveals_hint_after_pause() -> None:
    settings = PromptCompletionSettings(next_word="auto")
    app = GateNoteTestApp(settings=settings)
    panel = GateInputPanel(_note_request())
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        note = panel.query_one("#gate-input-note", GateNoteInput)
        note.focus()
        await pilot.pause()
        note.text = "Can you help me,"
        note.cursor_location = (0, len(note.text))
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert note.suggestion.startswith("implement")
        await pilot.press("i", "m")
        assert note.text == "Can you help me, im"
        assert note.suggestion.startswith("plement")
        await pilot.pause(0.6)
        assert note._next_word_ghost_visible() is True
        assert "[^T] word" in _note_hint(note)


async def test_gate_note_auto_midword_completes() -> None:
    settings = PromptCompletionSettings(next_word="auto")
    app = GateNoteTestApp(settings=settings)
    panel = GateInputPanel(_note_request())
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        note = panel.query_one("#gate-input-note", GateNoteInput)
        note.focus()
        await pilot.pause()
        note.text = "Can you help me impl"
        note.cursor_location = (0, len(note.text))
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert note.text == "Can you help me imple"
        assert note._next_word_ghost_visible() is True
        assert note.suggestion.startswith("ment")
