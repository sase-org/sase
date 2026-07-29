"""Selectable timeline widget for the Artifacts commits pane."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from sase.core.vcs_log_wire import AggregatedCommitWire
from sase.vcs_log.models import VcsLogResult
from sase.vcs_log.render import build_timeline_commit, build_timeline_day

from .entry_navigation import (
    ArtifactEntryTarget,
    prepend_jump_hint,
    prepend_mark_glyph,
)


def _commit_entry_target(entry: AggregatedCommitWire) -> ArtifactEntryTarget:
    """Return the cross-refresh identity for one repository commit."""
    return ("commit", entry.repo, entry.commit.full_id)


class CommitsTimeline(OptionList):
    """Day-grouped commit rows controlled by app-level Commits actions."""

    # Enter is registry-driven at the app level. Keep OptionList's arrow/page
    # bindings for accessibility while preventing its fixed Enter binding from
    # bypassing a configured ``commits_view_selected`` override.
    BINDINGS = [
        Binding("down", "cursor_down", "Down", show=False),
        Binding("end", "last", "Last", show=False),
        Binding("home", "first", "First", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    class SelectionChanged(Message):
        def __init__(self, commit_index: int) -> None:
            self.commit_index = commit_index
            super().__init__()

    class OpenRequested(Message):
        def __init__(self, commit_index: int) -> None:
            self.commit_index = commit_index
            super().__init__()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._commit_index_by_option: list[int | None] = []
        self._commits: tuple[AggregatedCommitWire, ...] = ()
        self._programmatic_update = False
        self._jump_hints: dict[ArtifactEntryTarget, str] = {}
        self._marks: set[ArtifactEntryTarget] = set()
        self._selection_callback: Callable[[int | None], None] | None = None

    def set_selection_callback(
        self,
        callback: Callable[[int | None], None],
    ) -> None:
        """Set the synchronous in-memory selection observer."""
        self._selection_callback = callback

    @property
    def selected_commit_index(self) -> int | None:
        highlighted = self.highlighted
        if highlighted is None or not (
            0 <= highlighted < len(self._commit_index_by_option)
        ):
            return None
        return self._commit_index_by_option[highlighted]

    def update_result(self, result: VcsLogResult) -> int | None:
        """Replace timeline rows while preserving the selected stable target."""
        selected_target = self.selected_entry_target
        self._commits = tuple(result.commits)
        self._jump_hints = {}
        self._rebuild_options(result, selected_target=selected_target)
        return self.selected_commit_index

    @property
    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        return tuple(_commit_entry_target(entry) for entry in self._commits)

    @property
    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        selected_index = self.selected_commit_index
        if selected_index is None or not 0 <= selected_index < len(self._commits):
            return None
        return _commit_entry_target(self._commits[selected_index])

    def select_entry_target(self, target: ArtifactEntryTarget) -> int | None:
        """Highlight a stable target without echoing a user navigation event."""
        option_index = self._option_for_target(target)
        if option_index is None:
            return None
        self.focus()
        self._programmatic_update = True
        try:
            self._assign_highlight(option_index)
        finally:
            self._programmatic_update = False
        return self.selected_commit_index

    def apply_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
        result: VcsLogResult,
    ) -> None:
        """Rebuild in-memory row prompts with transient entry hints."""
        selected_target = self.selected_entry_target
        self._jump_hints = dict(hints)
        self._rebuild_options(result, selected_target=selected_target)

    def clear_jump_hints(self, result: VcsLogResult) -> None:
        if not self._jump_hints:
            return
        selected_target = self.selected_entry_target
        self._jump_hints = {}
        self._rebuild_options(result, selected_target=selected_target)

    def apply_marks(
        self,
        marks: set[ArtifactEntryTarget],
        result: VcsLogResult,
    ) -> None:
        """Repaint mark glyphs without changing the selected commit."""
        selected_target = self.selected_entry_target
        self._marks = set(marks)
        self._rebuild_options(result, selected_target=selected_target)

    def _rebuild_options(
        self,
        result: VcsLogResult,
        *,
        selected_target: ArtifactEntryTarget | None,
    ) -> None:
        """Repaint the loaded timeline without performing data work."""

        options: list[Option] = []
        mapping: list[int | None] = []
        current_day: str | None = None
        for commit_index, entry in enumerate(self._commits):
            day, banner = build_timeline_day(entry.commit.timestamp)
            if day != current_day:
                options.append(
                    Option(banner, id=f"commit-day-{commit_index}", disabled=True)
                )
                mapping.append(None)
                current_day = day
            entry_target = _commit_entry_target(entry)
            prompt = prepend_jump_hint(
                prepend_mark_glyph(
                    build_timeline_commit(
                        entry,
                        result,
                        show_tags=False,
                        show_author=False,
                    ),
                    entry_target in self._marks,
                ),
                self._jump_hints.get(entry_target),
            )
            prompt.no_wrap = True
            prompt.overflow = "ellipsis"
            options.append(Option(prompt, id=f"commit-{commit_index}"))
            mapping.append(commit_index)

        if not options:
            message = "No commits match the current scope and filters."
            if result.warnings:
                message = result.warnings[0]
            options.append(Option(Text(f"  {message}", style="dim"), disabled=True))
            mapping.append(None)

        self._programmatic_update = True
        try:
            self.clear_options()
            self._commit_index_by_option = mapping
            self.add_options(options)
            highlight = self._option_for_target(selected_target)
            if highlight is None:
                highlight = next(
                    (
                        option_index
                        for option_index, index in enumerate(mapping)
                        if index is not None
                    ),
                    None,
                )
            self._assign_highlight(highlight)
        finally:
            self._programmatic_update = False

    def _assign_highlight(self, target: int | None) -> None:
        """Assign a guarded highlight and synchronously reveal its row."""
        self.highlighted = target
        self.scroll_to_highlight()

    def _option_for_target(self, target: ArtifactEntryTarget | None) -> int | None:
        if target is None:
            return None
        for option_index, commit_index in enumerate(self._commit_index_by_option):
            if (
                commit_index is not None
                and _commit_entry_target(self._commits[commit_index]) == target
            ):
                return option_index
        return None

    def watch_highlighted(self, highlighted: int | None) -> None:
        if self._programmatic_update:
            return
        super().watch_highlighted(highlighted)
        callback = self._selection_callback
        if callback is not None:
            callback(self.selected_commit_index)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self._programmatic_update or event.option_index is None:
            return
        index = self._commit_index_by_option[event.option_index]
        if index is not None:
            self.post_message(self.SelectionChanged(index))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_index is None:
            return
        index = self._commit_index_by_option[event.option_index]
        if index is not None:
            self.post_message(self.SelectionChanged(index))
            self.post_message(self.OpenRequested(index))


__all__ = ["CommitsTimeline"]
