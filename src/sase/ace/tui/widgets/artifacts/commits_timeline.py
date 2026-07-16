"""Selectable timeline widget for the Artifacts commits pane."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from sase.core.vcs_log_wire import AggregatedCommitWire
from sase.vcs_log.models import VcsLogResult
from sase.vcs_log.render import build_timeline_commit, build_timeline_day


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

    @property
    def selected_commit_index(self) -> int | None:
        highlighted = self.highlighted
        if highlighted is None or not (
            0 <= highlighted < len(self._commit_index_by_option)
        ):
            return None
        return self._commit_index_by_option[highlighted]

    def update_result(self, result: VcsLogResult) -> int | None:
        """Replace timeline rows while preserving the selected SHA."""
        selected_index = self.selected_commit_index
        selected_sha = (
            self._commits[selected_index].commit.full_id
            if selected_index is not None and selected_index < len(self._commits)
            else None
        )
        self._commits = tuple(result.commits)

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
            options.append(
                Option(
                    build_timeline_commit(entry, result),
                    id=f"commit-{commit_index}",
                )
            )
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
            target = self._option_for_sha(selected_sha)
            if target is None:
                target = next(
                    (
                        option_index
                        for option_index, index in enumerate(mapping)
                        if index is not None
                    ),
                    None,
                )
            self.highlighted = target
        finally:
            self._programmatic_update = False
        return self.selected_commit_index

    def _option_for_sha(self, sha: str | None) -> int | None:
        if sha is None:
            return None
        for option_index, commit_index in enumerate(self._commit_index_by_option):
            if (
                commit_index is not None
                and self._commits[commit_index].commit.full_id == sha
            ):
                return option_index
        return None

    def watch_highlighted(self, highlighted: int | None) -> None:
        if self._programmatic_update:
            return
        super().watch_highlighted(highlighted)

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
