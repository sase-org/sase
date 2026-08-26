"""Shared harnesses for prompt-history word completion tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.history.prompt_store import PromptEntry
from sase.history.prompt_word_index import PromptWordIndex, build_prompt_word_index

from ._completion_helpers import CompletionTestApp


def seeded_index(entries: list[tuple[str, str]]) -> PromptWordIndex:
    """Build a real :class:`PromptWordIndex` from ``(text, last_used)`` pairs."""
    return build_prompt_word_index(
        min_length=1,
        shard_limit=None,
        prompt_limit=None,
        shard_paths=[Path("history-word-completion-test.json")],
        load_shard_func=lambda _path: [
            PromptEntry(text=text, timestamp=last_used, last_used=last_used)
            for text, last_used in entries
        ],
    )


class RankedHistoryCompletionTestApp(CompletionTestApp):
    """Completion harness exercising the smart, index-backed ranking path."""

    def __init__(
        self,
        index: PromptWordIndex,
        *,
        deletions: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__()
        self.index = index
        self.deletions = deletions
        self.settings = PromptCompletionSettings(word_ranking="smart")
        self.warm_requests = 0

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings

    def history_prompt_word_index(self) -> PromptWordIndex | None:
        return self.index

    def history_prompt_word_deletions(self) -> frozenset[str]:
        return self.deletions

    def warm_history_prompt_words(self) -> None:
        self.warm_requests += 1

    def forget_history_prompt_word(self, word: str) -> None:
        """Mirror the real app's optimistic, index-preserving deletion."""
        from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

        self.forgotten_history_words.append(word)
        folded = word.casefold()
        self.deletions = frozenset(
            candidate for candidate in self.deletions if candidate.casefold() != folded
        ) | {word}
        for text_area in self.query(PromptTextArea):
            if (
                text_area._file_completion_active
                and text_area._completion_kind == HISTORY_WORD_COMPLETION_KIND
            ):
                text_area._refresh_file_completion_from_cursor()


class HistoryCompletionTestApp(CompletionTestApp):
    """Completion harness with an app-level MRU history-word list cache.

    Exercises the ``word_ranking: recent`` code path -- the plain
    list-of-spellings overload kept for callers and test harnesses that only
    have an MRU word list, not a warm :class:`PromptWordIndex`. Smart-ranked
    behavior is covered separately by ``RankedHistoryCompletionTestApp``.
    """

    def __init__(
        self,
        words: list[str] | None,
        *,
        settings: PromptCompletionSettings | None = None,
    ) -> None:
        super().__init__()
        self.words = words
        self.settings = settings or PromptCompletionSettings(word_ranking="recent")
        self.warm_requests = 0

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings

    def history_prompt_words(self) -> list[str] | None:
        return self.words

    def warm_history_prompt_words(self) -> None:
        self.warm_requests += 1


@pytest.fixture(autouse=True)
def skip_unrelated_vcs_catalog_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep history-word tests off the unrelated VCS catalog warm path."""
    monkeypatch.setattr(
        "sase.ace.tui.widgets._file_completion_base._warm_vcs_completion_catalogs",
        lambda: None,
    )
