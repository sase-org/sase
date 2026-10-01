"""Non-blocking next-word prediction accessor for prompt completion.

Gives widgets a keystroke-safe :meth:`_predict_next_words` over the app's
warm prediction model. A cold or missing model degrades to silence (``None``);
any prediction error disables the feature for the session and is logged once.
Words the user deleted from history are post-filtered in memory for
immediacy, truncating the ghost before a deleted word, so ``Ctrl+D`` takes
effect without waiting for a corpus rebuild.

The warm-model accessors live in
:class:`NextWordPredictionAccessMixin` (shared with the gate note editor);
this mixin only adds the prefix-rank helpers for context promotion.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from sase.ace.tui.widgets._file_completion_workers import FileCompletionWorkerMixin
from sase.ace.tui.widgets._next_word_prediction_access import (
    NextWordPredictionAccessMixin,
)

if TYPE_CHECKING:
    from sase.core.prompt_prediction_wire import PromptPrefixRankResult


class FileCompletionPredictionMixin(
    NextWordPredictionAccessMixin, FileCompletionWorkerMixin
):
    """Mixin providing warm next-word prediction access without disk I/O."""

    def _rank_prefix_context(
        self,
        text_before_word: str,
        prefix: str,
        *,
        limit: int | None = None,
    ) -> PromptPrefixRankResult | None:
        """Return prefix-rank matches for the current word, or ``None``.

        Silence covers ``next_word: off``, the cold model, a
        session-disabled feature, and any prediction failure (which disables
        the feature for the session and logs once). History-deleted words
        are dropped, so ``Ctrl+D`` forget applies to context promotion
        without waiting for a corpus rebuild.
        """
        from sase.ace.tui.widgets._prompt_context_ranking import CONTEXT_RANK_LIMIT
        from sase.core.prompt_prediction_wire import PromptPrefixRankRequest

        try:
            settings = getattr(self, "_prompt_completion_settings", None)
            if callable(settings):
                parsed = settings()
                mode = getattr(parsed, "next_word", "chain")
                if mode == "off":
                    return None
                if getattr(parsed, "word_ranking", "smart") != "smart":
                    return None
        except Exception:
            pass
        if self._prompt_prediction_session_disabled():
            return None
        model = self._prompt_prediction_model()
        if model is None:
            return None
        try:
            result = model.rank_prefix(
                PromptPrefixRankRequest(
                    text_before_word=text_before_word,
                    prefix=prefix,
                    project=self._prompt_prediction_project(text_before_word),
                    limit=limit if limit is not None else CONTEXT_RANK_LIMIT,
                )
            )
        except Exception:
            self._disable_prompt_prediction_for_session()
            return None
        return self._post_filter_deleted_matches(result)

    def _post_filter_deleted_matches(
        self, result: PromptPrefixRankResult
    ) -> PromptPrefixRankResult:
        """Drop history-deleted words from a prefix-rank result."""
        deletions = self._prediction_deleted_words()
        if not deletions:
            return result
        matches = [match for match in result.matches if match.key not in deletions]
        if len(matches) == len(result.matches):
            return result
        return replace(result, matches=matches)
