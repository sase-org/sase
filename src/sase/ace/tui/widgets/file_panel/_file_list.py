"""File list navigation and source selection for the agent file panel."""

import os
from dataclasses import dataclass

from rich.text import Text
from textual.worker import Worker

from sase.agent.status_buckets import status_bucket_for_values
from sase.plan_chain import PLAN_CHAIN_PLAN_SUFFIX, canonical_plan_chain_suffix

from ...graphics import is_supported_image_path
from ...models.agent import Agent
from ..prompt_panel._agent_commits import CommitDiffInfo, agent_commit_diffs
from ..prompt_panel._agent_context_common import WORKSPACE_GLYPH
from ..prompt_panel._agent_context_common import EXTERNAL_REPO_GLYPH
from ._linked_deltas import LinkedDeltaGroup, get_cached_linked_delta_groups
from ._messages import (
    FileListChanged,
    FileVisibilityChanged,
    _LIVE_DIFF_SENTINEL,
    commit_slot_id,
    commit_slot_index,
    file_cache,
    get_cache_key,
    is_commit_slot,
    is_linked_slot,
    linked_slot_id,
    linked_slot_repo_name,
)


@dataclass(frozen=True)
class FileSourceLabel:
    """Display label metadata for one file-panel page slot."""

    tag: str
    label: str


class FilePanelFileListMixin:
    """Mixin for file-panel page lists and current-source helpers."""

    _current_agent: Agent | None
    _current_worker: Worker[str | None] | None
    _file_list: list[str]
    _current_file_index: int
    _has_displayed_content: bool
    _last_file_content: str | None

    def set_file_list(self, files: list[str], start_index: int = 0) -> None:
        """Store the file list, reset index, and display a file.

        Args:
            files: Ordered list of file paths to make available for cycling.
            start_index: Initial file index to display (default 0).
        """
        # Cancel any running background worker to prevent it from overwriting
        # the static file display (e.g. stale live-diff from RUNNING phase)
        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        # Clear agent association so that the next update_display() call for a
        # different agent won't incorrectly see same_agent=True and skip the
        # full reset (which would leave this static file list on screen).
        self._current_agent = None

        if files == self._file_list and self._file_list and self._has_displayed_content:
            # Files unchanged — preserve the user's current_file_index regardless
            # of the caller's default start_index. Auto-refresh must not overwrite
            # a user selection driven by <ctrl+n>/<ctrl+p>.
            return

        # Remember the file the user is currently on so we can preserve the
        # selection across refreshes where the list has grown/shrunk but the
        # current file still exists.
        old_path: str | None = None
        if self._file_list and 0 <= self._current_file_index < len(self._file_list):
            old_path = self._file_list[self._current_file_index]

        self._reset_content_state()  # type: ignore[attr-defined]
        self._file_list = list(files)
        if old_path is not None and old_path in self._file_list:
            self._current_file_index = self._file_list.index(old_path)
        else:
            self._current_file_index = min(start_index, len(files) - 1) if files else 0
        self.post_message(  # type: ignore[attr-defined]
            FileListChanged(
                file_count=len(self._file_list),
                file_index=self._current_file_index,
            )
        )
        if files:
            self._display_file_at_current_index()

    def next_file(self) -> None:
        """Cycle to the next file in the list (wraps around)."""
        if len(self._file_list) <= 1:
            return
        self._current_file_index = (self._current_file_index + 1) % len(self._file_list)
        self._display_file_at_current_index()
        self.post_message(  # type: ignore[attr-defined]
            FileListChanged(
                file_count=len(self._file_list),
                file_index=self._current_file_index,
            )
        )

    def prev_file(self) -> None:
        """Cycle to the previous file in the list (wraps around)."""
        if len(self._file_list) <= 1:
            return
        self._current_file_index = (self._current_file_index - 1) % len(self._file_list)
        self._display_file_at_current_index()
        self.post_message(  # type: ignore[attr-defined]
            FileListChanged(
                file_count=len(self._file_list),
                file_index=self._current_file_index,
            )
        )

    @property
    def current_file_count(self) -> int:
        """Return the number of files in the file list."""
        return len(self._file_list)

    @property
    def current_file_index(self) -> int:
        """Return the current file index (0-based)."""
        return self._current_file_index

    @property
    def current_file_slots(self) -> tuple[str, ...]:
        """Return the current ordered file-panel page slots."""
        return tuple(self._file_list)

    def _display_file_at_current_index(self) -> None:
        """Display the file at the current index.

        Handles live diff, commit diff, linked diff, and static file page slots.
        """
        if not self._file_list:
            return
        path = self._file_list[self._current_file_index]
        if path == _LIVE_DIFF_SENTINEL:
            # Re-display the cached live diff
            if self._current_agent:
                cache_key = get_cache_key(self._current_agent)
                cache_entry = file_cache.get(cache_key)
                if cache_entry:
                    self._display_file_with_timestamp(  # type: ignore[attr-defined]
                        cache_entry.diff_output, cache_entry.fetch_time
                    )
            return
        if is_commit_slot(path):
            info = self._commit_diff_info_for_slot(path)
            if info is None:
                self._display_commit_diff_unavailable()
                return
            self.display_static_diff(info.diff_path)  # type: ignore[attr-defined]
            return
        if is_linked_slot(path):
            repo_name = linked_slot_repo_name(path)
            group = self._linked_group_for_repo(repo_name)
            if group is None:
                self.display_linked_diff_unavailable(repo_name)  # type: ignore[attr-defined]
                return
            self.display_linked_diff(  # type: ignore[attr-defined]
                group.repo_name,
                group.workspace_dir,
                group.diff_text,
                group.fetched_at,
                group.kind,
            )
            return
        self.display_static_file(path)  # type: ignore[attr-defined]

    def _desired_file_list(self, agent: Agent) -> tuple[list[str], str | None]:
        """Return the current canonical file-panel page list and default page."""
        pages: list[str] = []

        commit_diffs = agent_commit_diffs(agent)
        pages.extend(commit_slot_id(index) for index, _ in enumerate(commit_diffs))

        cache_entry = file_cache.get(get_cache_key(agent))
        suppress_live_diff = bool(commit_diffs) and _is_terminal_agent(agent)
        if (
            cache_entry is not None
            and bool(cache_entry.diff_output)
            and not suppress_live_diff
        ):
            pages.append(_LIVE_DIFF_SENTINEL)

        linked_groups = get_cached_linked_delta_groups(agent)
        pages.extend(
            linked_slot_id(group.repo_name) for group in linked_groups if group.entries
        )

        extra_files = list(agent.extra_files)
        pages.extend(extra_files)

        default_value = pages[0] if pages else None
        if (
            extra_files
            and canonical_plan_chain_suffix(agent.role_suffix) == PLAN_CHAIN_PLAN_SUFFIX
            and not agent.diff_path
        ):
            default_value = extra_files[0]
        return pages, default_value

    def _select_file_index(
        self,
        pages: list[str],
        *,
        preferred_value: str | None,
        default_value: str | None,
        fallback_index: int = 0,
    ) -> int:
        """Pick an index by current page value, then default page, then clamp."""
        if not pages:
            return 0
        if preferred_value is not None and preferred_value in pages:
            return pages.index(preferred_value)
        if default_value is not None and default_value in pages:
            return pages.index(default_value)
        return min(max(fallback_index, 0), len(pages) - 1)

    def _current_file_value(self) -> str | None:
        if self._file_list and 0 <= self._current_file_index < len(self._file_list):
            return self._file_list[self._current_file_index]
        return None

    def _linked_group_for_repo(self, repo_name: str) -> LinkedDeltaGroup | None:
        agent = self._current_agent
        if agent is None:
            return None
        for group in get_cached_linked_delta_groups(agent):
            if group.repo_name == repo_name:
                return group
        return None

    def _commit_diff_info_for_slot(self, slot: str) -> CommitDiffInfo | None:
        agent = self._current_agent
        if agent is None:
            return None
        try:
            index = commit_slot_index(slot)
        except (TypeError, ValueError):
            return None
        commit_diffs = agent_commit_diffs(agent)
        if index < 0 or index >= len(commit_diffs):
            return None
        return commit_diffs[index]

    def _commit_diff_path_for_slot(self, slot: str) -> str | None:
        info = self._commit_diff_info_for_slot(slot)
        return info.diff_path if info is not None else None

    def _display_commit_diff_unavailable(self) -> None:
        self._reset_content_state()  # type: ignore[attr-defined]
        text = Text("Commit diff is unavailable.\n", style="dim italic")
        self.update(text)  # type: ignore[attr-defined]
        self._has_displayed_content = True
        self._post_file_visibility(has_file=False)
        self._post_line_count_changed()  # type: ignore[attr-defined]

    def _current_linked_diff_changed(self) -> bool:
        current = self._current_file_value()
        if current is None or not is_linked_slot(current):
            return False
        group = self._linked_group_for_repo(linked_slot_repo_name(current))
        if group is None:
            return self._last_file_content is not None
        return group.diff_text != self._last_file_content

    def _reconcile_file_list(
        self,
        agent: Agent,
        *,
        allow_initial_display: bool,
    ) -> None:
        """Synchronize page slots with cached diff/link/artifact state."""
        self._current_agent = agent
        desired, default_value = self._desired_file_list(agent)
        current_value = self._current_file_value()

        if desired == self._file_list:
            if allow_initial_display and desired and not self._has_displayed_content:
                self._display_file_at_current_index()
            elif self._current_linked_diff_changed():
                scroll_pos = self._save_scroll_position()  # type: ignore[attr-defined]
                self._display_file_at_current_index()
                self._restore_scroll_position(scroll_pos)  # type: ignore[attr-defined]
            return

        old_index = self._current_file_index
        old_displayed = self._has_displayed_content
        self._file_list = list(desired)
        self._current_file_index = self._select_file_index(
            self._file_list,
            preferred_value=current_value,
            default_value=default_value,
            fallback_index=old_index,
        )
        new_value = self._current_file_value()

        self.post_message(  # type: ignore[attr-defined]
            FileListChanged(
                file_count=len(self._file_list),
                file_index=self._current_file_index,
            )
        )

        if not self._file_list:
            if allow_initial_display and current_value is not None:
                cache_entry = file_cache.get(get_cache_key(agent))
                if cache_entry is not None:
                    self._display_file_with_timestamp(  # type: ignore[attr-defined]
                        cache_entry.diff_output,
                        cache_entry.fetch_time,
                    )
                else:
                    self._post_file_visibility(has_file=False)
            return

        needs_render = new_value != current_value or not old_displayed
        if new_value is not None and is_linked_slot(new_value):
            needs_render = needs_render or self._current_linked_diff_changed()
        if allow_initial_display and needs_render:
            scroll_pos = self._save_scroll_position()  # type: ignore[attr-defined]
            self._display_file_at_current_index()
            if new_value == current_value:
                self._restore_scroll_position(scroll_pos)  # type: ignore[attr-defined]

    def _pick_up_extra_files(self, agent: Agent) -> None:
        """Backward-compatible wrapper for same-agent file-list reconciliation."""
        self._reconcile_file_list(agent, allow_initial_display=True)

    def _post_file_visibility(self, has_file: bool) -> None:
        """Post a FileVisibilityChanged message with current file list state."""
        file_count = len(self._file_list) if self._file_list else (1 if has_file else 0)
        self.post_message(  # type: ignore[attr-defined]
            FileVisibilityChanged(
                has_file=has_file,
                file_count=file_count,
                file_index=self._current_file_index,
            )
        )

    def get_current_file_path(self) -> str | None:
        """Return the expanded path of the currently displayed file, or None."""
        if self._file_list:
            path = self._file_list[self._current_file_index]
            if path == _LIVE_DIFF_SENTINEL or is_linked_slot(path):
                return None
            if is_commit_slot(path):
                diff_path = self._commit_diff_path_for_slot(path)
                return os.path.expanduser(diff_path) if diff_path else None
            return os.path.expanduser(path)
        return None

    def current_source_label(self) -> str | None:
        """Return a short label for the currently selected file-panel source."""
        current = self._current_file_value()
        if current is None:
            return None
        return self.source_label_for_slot(current).label

    def source_label_for_slot(self, slot: str) -> FileSourceLabel:
        """Return compact display metadata for a file-panel page slot."""
        if slot == _LIVE_DIFF_SENTINEL:
            return FileSourceLabel(tag="diff", label="diff")
        if is_commit_slot(slot):
            label = "commit diff"
            info = self._commit_diff_info_for_slot(slot)
            if info is not None:
                label = " ".join(
                    part for part in (info.repo_name, info.short_sha) if part
                )
                if not label:
                    label = "commit diff"
                if not info.is_primary:
                    glyph = (
                        EXTERNAL_REPO_GLYPH
                        if info.repo_kind == "external"
                        else WORKSPACE_GLYPH
                    )
                    label = f"{glyph} {label}"
            return FileSourceLabel(tag="git", label=label)
        if is_linked_slot(slot):
            repo_name = linked_slot_repo_name(slot)
            group = self._linked_group_for_repo(repo_name)
            glyph = (
                EXTERNAL_REPO_GLYPH
                if group is not None and group.kind == "external"
                else WORKSPACE_GLYPH
            )
            return FileSourceLabel(
                tag="repo",
                label=f"{glyph} {repo_name}",
            )
        expanded = os.path.expanduser(slot)
        label = os.path.basename(expanded) or expanded
        return FileSourceLabel(tag="file", label=label)

    def file_source_labels(self) -> tuple[FileSourceLabel, ...]:
        """Return display label metadata for all current file-panel page slots."""
        return tuple(self.source_label_for_slot(slot) for slot in self._file_list)

    def get_current_image_path(self) -> str | None:
        """Return the current existing image file path, or None."""
        path = self.get_current_file_path()
        if path is None:
            return None
        if not is_supported_image_path(path):
            return None
        if not os.path.exists(path):
            return None
        return path

    def get_current_content(self) -> str | None:
        """Return the last displayed file content, or None."""
        return self._last_file_content


def _is_terminal_agent(agent: Agent) -> bool:
    return status_bucket_for_values(agent.status) in {"Done", "Failed"}
