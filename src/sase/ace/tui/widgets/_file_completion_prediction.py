"""Non-blocking next-word prediction accessor for prompt completion.

Gives widgets a keystroke-safe :meth:`_predict_next_words` over the app's
warm prediction model. A cold or missing model degrades to silence (``None``);
any prediction error disables the feature for the session and is logged once.
Words the user deleted from history are post-filtered in memory for
immediacy, truncating the ghost before a deleted word, so ``Ctrl+D`` takes
effect without waiting for a corpus rebuild.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets._file_completion_workers import FileCompletionWorkerMixin

if TYPE_CHECKING:
    from sase.core.prompt_prediction_facade import PromptPredictionModel
    from sase.core.prompt_prediction_wire import PromptPredictionResult

log = logging.getLogger(__name__)

_prediction_error_logged = False


class FileCompletionPredictionMixin(FileCompletionWorkerMixin):
    """Mixin providing warm next-word prediction access without disk I/O."""

    def _prompt_prediction_model(self) -> PromptPredictionModel | None:
        """Return the app's warm prediction model without touching disk."""
        provider = getattr(self.app, "get_prompt_prediction_model", None)
        if not callable(provider):
            return None
        try:
            model = provider()
        except Exception:
            return None
        from sase.core.prompt_prediction_facade import PromptPredictionModel

        return model if isinstance(model, PromptPredictionModel) else None

    def _prompt_prediction_is_cold(self) -> bool:
        """Return whether the prediction model has not landed yet."""
        return self._prompt_prediction_model() is None

    def _schedule_prompt_prediction_load(self) -> None:
        """Ask the app cache to warm for a cold prediction request."""
        warmer = getattr(self.app, "warm_prompt_prediction", None)
        if callable(warmer):
            warmer()

    def _warm_prompt_prediction_cache(self) -> None:
        """Warm next-word prediction off the mount and keystroke paths."""
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        self._schedule_prompt_prediction_load()

    def _predict_next_words(
        self,
        text_before_cursor: str,
        *,
        limit: int = 5,
        max_words: int = 4,
        confidence: str = "balanced",
    ) -> PromptPredictionResult | None:
        """Predict next words for *text_before_cursor*, or ``None`` on silence.

        Silence covers the cold model, a session-disabled feature, and any
        prediction failure (which disables the feature for the session and
        logs once). The returned ghost is truncated before the first
        history-deleted word and deleted candidates are dropped.
        """
        try:
            settings = getattr(self, "_prompt_completion_settings", None)
            if callable(settings):
                mode = getattr(settings(), "next_word", "chain")
                if mode == "off":
                    return None
        except Exception:
            pass
        if self._prompt_prediction_session_disabled():
            return None
        model = self._prompt_prediction_model()
        if model is None:
            return None
        try:
            from sase.core.prompt_prediction_wire import PromptPredictionRequest

            result = model.predict(
                PromptPredictionRequest(
                    text_before_cursor=text_before_cursor,
                    project=self._prompt_prediction_project(text_before_cursor),
                    limit=limit,
                    max_words=max_words,
                    confidence=confidence,
                )
            )
        except Exception:
            self._disable_prompt_prediction_for_session()
            return None
        return self._post_filter_deleted_words(result)

    def _prompt_prediction_project(self, text_before_cursor: str) -> str | None:
        """Resolve the draft's project key without disk I/O."""
        provider = getattr(self.app, "get_prompt_prediction_project", None)
        if not callable(provider):
            return None
        try:
            project = provider(text_before_cursor)
        except Exception:
            return None
        return project if isinstance(project, str) and project else None

    def _prompt_prediction_session_disabled(self) -> bool:
        """Return whether the app disabled prediction for this session."""
        provider = getattr(self.app, "prompt_prediction_disabled", None)
        if not callable(provider):
            return False
        try:
            return bool(provider())
        except Exception:
            return False

    def _disable_prompt_prediction_for_session(self) -> None:
        """Disable app prediction for the session and log the first failure."""
        global _prediction_error_logged  # noqa: PLW0603
        disable = getattr(self.app, "disable_prompt_prediction", None)
        if callable(disable):
            try:
                disable()
            except Exception:
                pass
        if not _prediction_error_logged:
            _prediction_error_logged = True
            log.exception("Prompt prediction failed; disabled for this session")

    def _post_filter_deleted_words(
        self, result: PromptPredictionResult
    ) -> PromptPredictionResult:
        """Truncate the ghost and candidates at history-deleted words."""
        deletions = self._prediction_deleted_words()
        if not deletions:
            return result
        ghost = _truncate_before_deleted(result.ghost, deletions)
        candidates = [
            candidate
            for candidate in result.candidates
            if candidate.key not in deletions
        ]
        if ghost == result.ghost and len(candidates) == len(result.candidates):
            return result
        return replace(result, ghost=ghost, candidates=candidates)

    def _prediction_deleted_words(self) -> frozenset[str]:
        """Return casefolded history-deleted words without touching disk."""
        provider = getattr(self.app, "history_prompt_word_deletions", None)
        if not callable(provider):
            return frozenset()
        try:
            deletions = provider()
        except Exception:
            return frozenset()
        if not isinstance(deletions, frozenset):
            return frozenset()
        return frozenset(word.casefold() for word in deletions)


def _truncate_before_deleted(ghost: list[str], deletions: frozenset[str]) -> list[str]:
    """Cut *ghost* before its first history-deleted word."""
    kept: list[str] = []
    for word in ghost:
        if word.casefold() in deletions:
            break
        kept.append(word)
    return kept
