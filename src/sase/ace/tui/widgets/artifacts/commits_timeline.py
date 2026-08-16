"""Selectable timeline widget for the Artifacts Stitches pane."""

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

from ..._artifact_tab_model import PaneGroupingModeDecl
from ...models.artifact_groups import build_grouped_rows
from ...models.group_fold import GroupFoldRegistry
from .entry_navigation import (
    ArtifactEntryTarget,
    prepend_jump_hint,
    prepend_mark_glyph,
    prewarm_option_render_cache,
    reveal_option_list_highlight,
)
from .group_banner import format_group_banner_option
from .types import ARTIFACTS_ACCENTS

STITCHES_PANE_ID = "stitches"


def commit_row_target(entry: AggregatedCommitWire) -> ArtifactEntryTarget:
    """Return the cross-refresh identity for one repository commit."""
    return ArtifactEntryTarget(
        pane_id=STITCHES_PANE_ID,
        parts=(entry.repo, entry.commit.full_id),
    )


def commit_key_value(entry: AggregatedCommitWire, mode_id: str) -> str:
    if mode_id == "by_date":
        label, _banner = build_timeline_day(entry.commit.timestamp)
        return label
    if mode_id == "by_repo":
        return entry.repo
    if mode_id == "by_author":
        return entry.commit.author_name
    return ""


def commit_group_label(mode_id: str, value: str) -> str:
    if mode_id == "by_repo":
        return value or "(unknown repo)"
    if mode_id == "by_author":
        return value or "(unknown author)"
    return value or "Unknown"


class CommitsTimeline(OptionList):
    """Day-grouped commit rows controlled by app-level Stitches actions."""

    # Enter is registry-driven at the app level. Keep OptionList's arrow/page
    # bindings for accessibility while preventing its fixed Enter binding from
    # bypassing a configured ``stitches_view_selected`` override.
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
        self._entry_targets: tuple[ArtifactEntryTarget, ...] = ()
        self._nav_targets: tuple[ArtifactEntryTarget, ...] = ()
        self._option_by_target: dict[ArtifactEntryTarget, int] = {}
        self._banner_target_by_option_index: dict[int, ArtifactEntryTarget] = {}
        self._programmatic_update = False
        self._render_cache_warmed = False
        self._jump_hints: dict[ArtifactEntryTarget, str] = {}
        self._marks: set[ArtifactEntryTarget] = set()
        self._selection_callback: Callable[[int | None], None] | None = None
        self._group_mode: PaneGroupingModeDecl | None = None
        self._group_fold_registry: GroupFoldRegistry | None = None
        self._group_accent: str = ARTIFACTS_ACCENTS["stitches"]

    def set_selection_callback(
        self,
        callback: Callable[[int | None], None],
    ) -> None:
        """Set the synchronous in-memory selection observer."""
        self._selection_callback = callback

    def set_grouping(
        self,
        *,
        mode: PaneGroupingModeDecl | None,
        fold_registry: GroupFoldRegistry | None,
        accent: str,
    ) -> None:
        """Adopt the active grouping mode/registry for the next rebuild."""
        self._group_mode = mode
        self._group_fold_registry = fold_registry
        self._group_accent = accent

    def prewarm_render_cache(self) -> None:
        """Warm bounded row renders for the current focus/style state."""
        self._render_cache_warmed = prewarm_option_render_cache(self)

    def ensure_render_cache_warmed(self) -> None:
        """Warm row renders once a concrete scroll region is available."""
        if not self._render_cache_warmed:
            self.prewarm_render_cache()

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
        self._entry_targets = tuple(commit_row_target(entry) for entry in self._commits)
        self._jump_hints = {}
        known_group_keys = self._rebuild_options(
            result, selected_target=selected_target
        )
        if self._group_fold_registry is not None:
            self._group_fold_registry.clear_unknown(known_group_keys)
        return self.selected_commit_index

    @property
    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        return self._nav_targets

    @property
    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        selected_index = self.selected_commit_index
        if selected_index is not None and 0 <= selected_index < len(self._commits):
            return self._entry_targets[selected_index]
        highlighted = self.highlighted
        if highlighted is None:
            return None
        return self._banner_target_by_option_index.get(highlighted)

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Highlight a stable target without echoing a user navigation event."""
        option_index = self._option_for_target(target)
        if option_index is None:
            return False
        self.focus()
        self._programmatic_update = True
        try:
            self._assign_highlight(option_index)
        finally:
            self._programmatic_update = False
        return True

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
    ) -> tuple[tuple[str, ...], ...]:
        """Repaint the loaded timeline without performing data work.

        Returns the known group keys produced this pass, for the caller to
        feed into :meth:`GroupFoldRegistry.clear_unknown`.
        """

        options: list[Option] = []
        mapping: list[int | None] = []
        option_by_target: dict[ArtifactEntryTarget, int] = {}
        nav_targets: list[ArtifactEntryTarget] = []
        banner_target_by_option_index: dict[int, ArtifactEntryTarget] = {}
        mode = self._group_mode
        known_group_keys: tuple[tuple[str, ...], ...] = ()

        def _emit_commit(commit_index: int) -> None:
            entry = self._commits[commit_index]
            entry_target = self._entry_targets[commit_index]
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
            option_by_target[entry_target] = len(options) - 1
            nav_targets.append(entry_target)

        if mode is None:
            for commit_index in range(len(self._commits)):
                _emit_commit(commit_index)
        else:
            grouped = build_grouped_rows(
                self._commits,
                pane_id=STITCHES_PANE_ID,
                mode_id=mode.id,
                keys=(mode.id,),
                key_values=lambda entry: (commit_key_value(entry, mode.id),),
                label_for=lambda _level, value: commit_group_label(mode.id, value),
                target_for=commit_row_target,
                fold_registry=self._group_fold_registry,
            )
            known_group_keys = grouped.known_group_keys
            for grouped_row in grouped.rows:
                if grouped_row.kind == "banner" and grouped_row.banner is not None:
                    banner = grouped_row.banner
                    options.append(
                        format_group_banner_option(
                            banner,
                            accent=self._group_accent,
                            hint_char=self._jump_hints.get(banner.target),
                        )
                    )
                    mapping.append(None)
                    if banner.collapsed:
                        banner_index = len(options) - 1
                        banner_target_by_option_index[banner_index] = banner.target
                        option_by_target[banner.target] = banner_index
                        nav_targets.append(banner.target)
                    continue
                assert grouped_row.item_index is not None
                _emit_commit(grouped_row.item_index)

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
            self._option_by_target = option_by_target
            self._banner_target_by_option_index = banner_target_by_option_index
            self._nav_targets = tuple(nav_targets)
            self.add_options(options)
            self._render_cache_warmed = False
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
            self.prewarm_render_cache()
        finally:
            self._programmatic_update = False
        return known_group_keys

    def _assign_highlight(self, target: int | None) -> None:
        """Assign a guarded highlight and synchronously reveal its row."""
        self.highlighted = target
        reveal_option_list_highlight(self)

    def _option_for_target(self, target: ArtifactEntryTarget | None) -> int | None:
        if target is None:
            return None
        return self._option_by_target.get(target)

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


__all__ = [
    "STITCHES_PANE_ID",
    "CommitsTimeline",
    "commit_group_label",
    "commit_key_value",
    "commit_row_target",
]
