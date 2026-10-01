"""Mid-word autosuggest from the core word completion.

Owns the ``auto``-mode trigger for typed word characters, the
suffix-plus-continuation composition of gated ``complete_current_word``
results as an inline ghost or border peek, the mid-word peek accepts
(which finish the typed word via the suffix, never by re-inserting the
whole word), and the keystroke-latency guard: typing-triggered requests
run synchronously while ``len(text_before_cursor)`` fits
``NEXT_WORD_SYNC_MAX_DRAFT_CHARS`` and otherwise defer off the Textual
pump through a thin timer plus a pump-free ``asyncio.to_thread``
predict (plan ``202609/next_word_autosuggest.md`` §8.6).

Sits between ``NextWordGhostPeekMixin`` (peek display, auto trigger,
accepts) and ``NextWordGhostStateMixin`` (ghost state, gating, reveal
scheduling): the peek layer delegates typed word characters here, and
the prompt-only chain layer drives composition through
:tmeth:`_compose_next_word_midword_result`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.ace.tui.widgets._next_word_ghost_state import (
    NEXT_WORD_GHOST_LIMIT,
    NEXT_WORD_SYNC_MAX_DRAFT_CHARS,
    NextWordGhostStateMixin,
)
from sase.ace.tui.widgets.next_word_completion import (
    NextWordGhost,
    build_midword_ghost_text,
    fit_midword_ghost_with_tail,
    midword_peek_words,
    next_word_leading_separator,
)
from sase.ace.tui.widgets.next_word_placement import (
    NextWordPlacement,
    classify_next_word_placement,
    next_word_midword_eligible,
    next_word_rest_of_line,
)
from sase.core.prompt_prediction_wire import PromptPredictionRequest

if TYPE_CHECKING:
    from sase.ace.tui.widgets.next_word_placement import NextWordPeek
    from sase.core.prompt_prediction_facade import PromptPredictionModel
    from sase.core.prompt_prediction_wire import (
        PromptPredictionResult,
        PromptPredictionWordCompletion,
    )

log = logging.getLogger(__name__)


class NextWordMidwordMixin(NextWordGhostStateMixin):
    """Mid-word trigger, composition, deferred requests, and accepts."""

    if TYPE_CHECKING:
        _next_word_ghost: NextWordGhost | None
        _next_word_hint: Any
        _next_word_peek: NextWordPeek | None
        _next_word_midword_generation: int
        _next_word_midword_timer: Any | None
        suggestion: str

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _replace_absolute_range(
            self,
            start_offset: int,
            end_offset: int,
            replacement: str,
        ) -> None: ...
        def _prompt_completion_settings(self) -> Any: ...
        def _anchor_next_word_chain(
            self, *, midword: bool, typed: bool = False
        ) -> tuple[str, int] | None: ...
        def _arm_next_word_chain(
            self,
            *,
            reveal: Literal["immediate", "delayed"] = "immediate",
            complete_current_word: bool = False,
            typed: bool = False,
        ) -> None: ...
        def _set_next_word_peek(
            self,
            words: list[str],
            *,
            reveal: Literal["immediate", "delayed"] = "immediate",
            word_completion: PromptPredictionWordCompletion | None = None,
        ) -> bool: ...

        def _next_word_settings(self) -> tuple[str, int, str]: ...
        def _next_word_ghost_allowed(self) -> bool: ...
        def _next_word_ghost_visible(self) -> bool: ...
        def _next_word_peek_visible(self) -> bool: ...
        def _next_word_on_last_wrapped_row(self) -> bool: ...
        def _next_word_available_width(self) -> int: ...
        def _schedule_next_word_reveal(self, text: str, cursor_offset: int) -> None: ...
        def _cancel_next_word_reveal(self) -> None: ...
        def _show_next_word_ghost_hint(self) -> None: ...
        def _hide_next_word_hint(self) -> None: ...
        def _prompt_prediction_model(self) -> PromptPredictionModel | None: ...
        def _prompt_prediction_project(self, text_before_cursor: str) -> str | None: ...
        def _prompt_prediction_session_disabled(self) -> bool: ...
        def _schedule_prompt_prediction_load(self) -> None: ...
        def _post_filter_deleted_words(
            self, result: PromptPredictionResult
        ) -> PromptPredictionResult: ...
        def _disable_prompt_prediction_for_session(self) -> None: ...

    def _maybe_auto_next_word_midword(self, character: str | None) -> bool:
        """Show a gated mid-word guess after a typed word character.

        In ``auto`` mode, a typed word character with no word character
        after the cursor requests ``complete_current_word`` from the
        core. A still-valid consumed ghost is kept and makes no request.
        Typing inside a word stays silent. Chain mode never guesses
        mid-word. Drafts past ``NEXT_WORD_SYNC_MAX_DRAFT_CHARS`` defer
        off the pump instead of predicting synchronously.
        """
        if character is None or len(character) != 1 or not character.isprintable():
            return False
        if not (character.isalnum() or character in {"-", "_", "'", "’"}):
            return False
        mode, _, _ = self._next_word_settings()
        if mode != "auto":
            return False
        if self._next_word_ghost_visible() or self._next_word_peek_visible():
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        if not next_word_midword_eligible(text, offset):
            return False
        if not self._next_word_ghost_allowed():
            return False
        if len(text[:offset]) > NEXT_WORD_SYNC_MAX_DRAFT_CHARS:
            self._defer_next_word_midword_request(text, offset)
            return False
        self._arm_next_word_chain(
            reveal="delayed", complete_current_word=True, typed=True
        )
        return self._next_word_ghost_visible() or self._next_word_peek_visible()

    def _compose_next_word_midword_result(
        self,
        result: PromptPredictionResult | None,
        *,
        reveal: Literal["immediate", "delayed"] = "immediate",
    ) -> bool:
        """Compose a mid-word result as ghost or peek; return success.

        The inline ghost is the casing-preserving suffix plus, when a
        gated continuation follows, a space and the continuation words;
        the peek's first word is the completed word. Old-core safety: a
        completion request answered without ``word_completion`` shows
        nothing, because a plain next-word ghost after a half-typed word
        would be a wrong guess. An exact word with no continuation is
        silence too: there is nothing to offer.
        """
        if result is None or not getattr(result, "confident", False):
            self._hide_next_word_hint()
            return False
        completion = getattr(result, "word_completion", None)
        if completion is None or not getattr(completion, "word", ""):
            self._hide_next_word_hint()
            return False
        continuation = [word for word in (result.ghost or []) if word]
        if not build_midword_ghost_text(completion.suffix or "", continuation):
            self._hide_next_word_hint()
            return False
        if self._set_next_word_midword_ghost(
            completion.suffix or "", continuation, reveal=reveal
        ):
            return True
        _, max_words, _ = self._next_word_settings()
        if self._set_next_word_peek(
            midword_peek_words(completion.word, continuation, max_words),
            reveal=reveal,
            word_completion=completion,
        ):
            return True
        self._hide_next_word_hint()
        return False

    def _set_next_word_midword_ghost(
        self,
        suffix: str,
        continuation: list[str],
        *,
        reveal: Literal["immediate", "delayed"] = "immediate",
    ) -> bool:
        """Fit a suffix-plus-continuation guess as the ghost; return success.

        Only the inline placements render: ``peek`` and ``none`` return
        ``False`` so the caller falls through to the border peek. A
        ``delayed`` reveal shows the ghost text at once but waits for the
        reveal beat before showing its hint.
        """
        _, max_words, _ = self._next_word_settings()
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        placement = classify_next_word_placement(text, offset)
        if placement not in (
            NextWordPlacement.INLINE_EOL,
            NextWordPlacement.INLINE_TAIL,
        ):
            return False
        if not self._next_word_on_last_wrapped_row():
            return False
        rest = next_word_rest_of_line(text, offset)
        tail = "" if placement is NextWordPlacement.INLINE_EOL else rest
        available = self._next_word_available_width()
        fitted = fit_midword_ghost_with_tail(
            suffix, continuation, available, max_words, tail
        )
        if not fitted:
            return False
        self._next_word_ghost = NextWordGhost(anchor_offset=offset, full_text=fitted)
        self._next_word_peek = None
        try:
            self.suggestion = fitted
        except Exception:
            self._next_word_ghost = None
            return False
        if reveal == "delayed":
            self._schedule_next_word_reveal(text, offset)
        else:
            self._cancel_next_word_reveal()
            self._show_next_word_ghost_hint()
        return True

    def _next_word_midword_debounce_s(self) -> float:
        """Return the deferred mid-word debounce in seconds."""
        getter = getattr(self, "_prompt_completion_settings", None)
        try:
            raw = getattr(getter(), "debounce_ms", 90) if callable(getter) else 90
            debounce_ms = float(raw)
        except (TypeError, ValueError):
            debounce_ms = 90.0
        return max(0.0, debounce_ms / 1000.0)

    def _cancel_next_word_midword_request(self) -> None:
        """Supersede a pending deferred mid-word request, if any."""
        generation = int(getattr(self, "_next_word_midword_generation", 0) or 0) + 1
        self._next_word_midword_generation = generation
        timer = getattr(self, "_next_word_midword_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
            self._next_word_midword_timer = None

    def _defer_next_word_midword_request(self, text: str, cursor_offset: int) -> None:
        """Arm a mid-word chain without predicting, then request off the pump.

        Long drafts stay out of the keystroke path: a thin timer fires
        after the debounce and spawns a pump-free ``asyncio.to_thread``
        predict whose result applies only when its snapshot (generation,
        text, cursor) is still current.
        """
        anchored = self._anchor_next_word_chain(midword=True, typed=True)
        if anchored is None:
            return
        snapshot_text, snapshot_offset = anchored
        generation = int(getattr(self, "_next_word_midword_generation", 0) or 0)
        try:
            self._next_word_midword_timer = self.set_timer(
                self._next_word_midword_debounce_s(),
                lambda: self._fire_next_word_midword_timer(
                    generation, snapshot_text, snapshot_offset
                ),
            )
        except Exception:
            self._next_word_midword_timer = None

    def _fire_next_word_midword_timer(
        self,
        generation: int,
        text: str,
        cursor_offset: int,
    ) -> None:
        """Spawn the deferred mid-word predict when still current.

        The callback stays thin and synchronous (tui_perf rule 2): it
        only re-reads text and cursor, captures the frozen model handle
        and request on the UI thread, and launches the slow predict as
        a pump-free task. App access never leaves this thread.
        """
        self._next_word_midword_timer = None
        if generation != getattr(self, "_next_word_midword_generation", 0):
            return
        try:
            current_text = self.text
            current_offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return
        if current_text != text or current_offset != cursor_offset:
            return
        if self._next_word_ghost_visible() or self._next_word_peek_visible():
            return
        if not self._next_word_ghost_allowed():
            return
        if self._prompt_prediction_session_disabled():
            return
        model = self._prompt_prediction_model()
        if model is None:
            try:
                self._schedule_prompt_prediction_load()
            except Exception:
                pass
            return
        _, max_words, confidence = self._next_word_settings()
        try:
            project = self._prompt_prediction_project(text[:cursor_offset])
        except Exception:
            project = None
        request = PromptPredictionRequest(
            text_before_cursor=text[:cursor_offset],
            project=project,
            limit=NEXT_WORD_GHOST_LIMIT,
            max_words=max_words,
            confidence=confidence,
            complete_current_word=True,
        )
        task = spawn_pump_free_task(
            self,
            self._run_next_word_midword_request(
                generation, text, cursor_offset, model, request
            ),
            name="next-word-midword",
            registry_attr="_next_word_midword_async_tasks",
        )
        if task is None:
            try:
                result = model.predict(request)
            except Exception:
                return
            self._apply_next_word_midword_result(
                generation, text, cursor_offset, result
            )

    async def _run_next_word_midword_request(
        self,
        generation: int,
        text: str,
        cursor_offset: int,
        model: PromptPredictionModel,
        request: PromptPredictionRequest,
    ) -> None:
        """Predict off the pump, then apply on the loop when still current.

        The frozen model handle is safe to call off-thread: concurrent
        worker-thread predicts return results identical to the UI-thread
        call. Only the ``model.predict`` call leaves the loop thread.
        """
        try:
            result = await asyncio.to_thread(model.predict, request)
        except Exception:
            self._apply_next_word_midword_error(generation, text, cursor_offset)
            return
        self._apply_next_word_midword_result(generation, text, cursor_offset, result)

    def _apply_next_word_midword_error(
        self,
        generation: int,
        text: str,
        cursor_offset: int,
    ) -> None:
        """Disable prediction for the session when a deferred request fails."""
        if generation != getattr(self, "_next_word_midword_generation", 0):
            return
        try:
            current_text = self.text
            current_offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return
        if current_text != text or current_offset != cursor_offset:
            return
        try:
            self._disable_prompt_prediction_for_session()
        except Exception:
            log.exception("Mid-word prediction failed and could not disable")

    def _apply_next_word_midword_result(
        self,
        generation: int,
        text: str,
        cursor_offset: int,
        result: PromptPredictionResult,
    ) -> None:
        """Compose a deferred mid-word result when its snapshot is current."""
        if generation != getattr(self, "_next_word_midword_generation", 0):
            return
        try:
            current_text = self.text
            current_offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return
        if current_text != text or current_offset != cursor_offset:
            return
        try:
            filtered = self._post_filter_deleted_words(result)
        except Exception:
            filtered = result
        self._compose_next_word_midword_result(filtered, reveal="delayed")

    def _accept_next_word_midword_peek_one(self) -> bool:
        """Finish the typed word from a mid-word peek, then predict again.

        Inserts the completion suffix only: the typed prefix stays, so the
        word is finished without duplication. An already-complete word
        (empty suffix) takes the next preview word with the menu
        separator rules instead, mirroring the exact-word ghost. One undo
        step, then predicts again in the same handler, so there is no
        flicker.
        """
        peek = getattr(self, "_next_word_peek", None)
        completion = getattr(peek, "word_completion", None)
        if peek is None or not peek.words or completion is None:
            return False
        if not self._next_word_peek_visible():
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        suffix = completion.suffix or ""
        if suffix:
            insertion = suffix
        else:
            if len(peek.words) < 2 or not peek.words[1]:
                return False
            insertion = f"{next_word_leading_separator(text[:offset])}{peek.words[1]}"
        try:
            self._replace_absolute_range(offset, offset, insertion)
        except Exception:
            return False
        self._arm_next_word_chain()
        return True

    def _accept_next_word_midword_peek_all(self) -> bool:
        """Insert a mid-word peek's suffix plus every preview word, then re-arm.

        One undo step; the composed insertion mirrors the mid-word ghost
        text the same guess would have shown inline.
        """
        peek = getattr(self, "_next_word_peek", None)
        completion = getattr(peek, "word_completion", None)
        if peek is None or not peek.words or completion is None:
            return False
        if not self._next_word_peek_visible():
            return False
        rest = [word for word in peek.words[1:] if word]
        insertion = (completion.suffix or "") + (f" {' '.join(rest)}" if rest else "")
        if not insertion:
            return False
        try:
            offset = self._absolute_offset(self.cursor_location)
            self._replace_absolute_range(offset, offset, insertion)
        except Exception:
            return False
        self._arm_next_word_chain()
        return True


__all__ = ["NextWordMidwordMixin"]
