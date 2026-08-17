"""Shared harnesses for ranked placeholder-completion tests."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.history.prompt_placeholders import (
    CommonPlaceholderIndex,
    _PlaceholderEntry,
)

from ._completion_helpers import CompletionTestApp


def placeholder_entry(
    text: str,
    *,
    count: int,
    last_used: str,
    context: dict[str, int] | None = None,
    context_uses: int | None = None,
) -> _PlaceholderEntry:
    bag = {} if context is None else dict(context)
    return _PlaceholderEntry(
        text=text,
        count=count,
        last_used=last_used,
        context_uses=count if context_uses is None else context_uses,
        context=bag,
    )


def placeholder_index(
    *entries: _PlaceholderEntry,
    prompt_count: int,
    context_frequency: dict[str, int] | None = None,
) -> CommonPlaceholderIndex:
    return CommonPlaceholderIndex(
        entries=entries,
        prompt_count=prompt_count,
        context_frequency={} if context_frequency is None else dict(context_frequency),
        max_count=max((entry.count for entry in entries), default=0),
    )


def related_over_frequent_index() -> CommonPlaceholderIndex:
    """A store where the related tag is neither the most used nor the newest.

    Entries are already in stored display order (count desc, then recency),
    so ``recent`` mode keeps ``worker`` first and smart ranking has to flip
    it.
    """
    return placeholder_index(
        placeholder_entry(
            "worker",
            count=4,
            last_used="260815_000000",
            context={"filler": 4},
        ),
        placeholder_entry(
            "phase title",
            count=2,
            last_used="260813_000000",
            context={
                "monitor": 2,
                "bravo": 2,
                "charlie": 2,
                "delta": 2,
            },
        ),
        prompt_count=16,
        context_frequency={
            "monitor": 2,
            "bravo": 2,
            "charlie": 2,
            "delta": 2,
            "filler": 4,
        },
    )


class RankedPlaceholderCompletionTestApp(CompletionTestApp):
    """Completion harness exercising the index-backed ranking path."""

    def __init__(
        self,
        index: CommonPlaceholderIndex | None,
        *,
        settings: PromptCompletionSettings | None = None,
    ) -> None:
        texts = None if index is None else [entry.text for entry in index.entries]
        super().__init__(common_placeholders=texts)
        self._index = index
        self.settings = settings or PromptCompletionSettings(
            placeholder_ranking="smart"
        )

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings

    def common_placeholder_index(self) -> CommonPlaceholderIndex | None:
        return self._index

    def publish_common_placeholder_index(self, index: CommonPlaceholderIndex) -> None:
        """Stand in for a warm index landing while a menu is already open."""
        self._index = index
        self.publish_common_placeholders([entry.text for entry in index.entries])

    def forget_common_placeholder(self, text: str) -> None:
        """Mirror the real app's optimistic index drop, then refresh the menu."""
        if self._index is not None:
            remaining = tuple(
                entry for entry in self._index.entries if entry.text != text
            )
            self._index = CommonPlaceholderIndex(
                entries=remaining,
                prompt_count=self._index.prompt_count,
                context_frequency=self._index.context_frequency,
                max_count=max((entry.count for entry in remaining), default=0),
            )
        super().forget_common_placeholder(text)
