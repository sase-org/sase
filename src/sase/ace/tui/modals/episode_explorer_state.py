"""State and rendering methods for the Episode Explorer modal."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.core.episode_wire import (
    EpisodeSourceRefWire,
    EpisodeWire,
    episode_wire_from_dict,
)
from sase.memory.episodes.index import project_episodes_dir
from sase.memory.episodes.inventory import EpisodeInventoryItem
from sase.memory.episodes.storage import EPISODE_JSON_FILE_NAME

from .episode_explorer_filtering import (
    display_rows,
    matches_filters,
    range_bounds,
)
from .episode_explorer_rendering import detail_text, row_text
from .episode_explorer_types import (
    EpisodeExplorerDisplayRow,
    EpisodeExplorerFilters,
    EpisodeExplorerEdgeMode,
    EpisodeExplorerView,
    VIEWS,
)


class EpisodeExplorerStateMixin(ModalScreen[None]):
    """Render cached episode state and derive current selections."""

    _project: str
    _projects_root: Path | None
    _today: date
    _filters: EpisodeExplorerFilters
    _items: list[EpisodeInventoryItem]
    _visible_rows: list[EpisodeExplorerDisplayRow]
    _view: EpisodeExplorerView
    _edge_mode: EpisodeExplorerEdgeMode
    _episode_cache: dict[str, EpisodeWire]
    _verify_status: dict[str, str]
    _source_index: dict[str, int]
    _loading: bool
    _loaded_once: bool
    _error: str | None
    _verify_worker: object

    def _apply_filters_from_cache(
        self, *, select_episode_id: str | None = None
    ) -> None:
        previous = select_episode_id or self._selected_display_episode_id()
        filtered = [
            item
            for item in self._items
            if matches_filters(item, self._filters, today=self._today)
        ]
        self._visible_rows = display_rows(filtered, self._filters.status)
        self._refresh_static_chrome()
        self._refresh_options(previous)
        self._render_selected_detail()

    def _refresh_options(self, previous_episode_id: str | None) -> None:
        option_list = self.query_one("#episode-explorer-list", OptionList)
        option_list.clear_options()
        for index, row in enumerate(self._visible_rows):
            option_list.add_option(Option(row_text(row), id=f"episode-row-{index}"))
        if not self._visible_rows:
            option_list.highlighted = None
            return
        target_index = 0
        if previous_episode_id:
            for index, row in enumerate(self._visible_rows):
                if row.display_episode_id == previous_episode_id:
                    target_index = index
                    break
        option_list.highlighted = target_index

    def _render_selected_detail(self) -> None:
        detail = self.query_one("#episode-explorer-detail", Static)
        row = self._selected_row()
        if self._loading:
            detail.update("Loading episode inventory...")
            return
        if self._error:
            detail.update(f"Episode inventory error: {self._error}")
            return
        if row is None:
            if self._loaded_once:
                detail.update("No episodes match the current filters.")
            else:
                detail.update("Episode inventory has not loaded yet.")
            return
        episode = self._load_episode_for_row(row)
        if episode is None:
            return
        width = max(72, min(110, self.size.width - 42 if self.size.width else 88))
        verify_status = self._verify_status.get(episode.episode_id, "not checked")
        current_source = (
            self._current_source(episode=episode) if self._view == "sources" else None
        )
        detail.update(
            detail_text(
                row,
                episode,
                view=self._view,
                edge_mode=self._edge_mode,
                verify_status=verify_status,
                width=width,
                current_source=current_source,
            )
        )
        try:
            self.query_one(
                "#episode-explorer-detail-scroll", VerticalScroll
            ).scroll_home(animate=False)
        except Exception:
            return

    def _render_loading(self) -> None:
        self.query_one("#episode-explorer-detail", Static).update(
            "Loading episode inventory..."
        )

    def _load_episode_for_row(
        self,
        row: EpisodeExplorerDisplayRow,
    ) -> EpisodeWire | None:
        cached = self._episode_cache.get(row.canonical_episode_id)
        if cached is not None:
            return cached
        episode_path = (
            project_episodes_dir(self._project, projects_root=self._projects_root)
            / row.canonical_episode_id
            / EPISODE_JSON_FILE_NAME
        )
        try:
            payload = json.loads(episode_path.read_text(encoding="utf-8"))
            episode = episode_wire_from_dict(payload)
        except Exception as exc:
            self.query_one("#episode-explorer-detail", Static).update(
                f"Failed to read {episode_path}: {exc}"
            )
            return None
        self._episode_cache[row.canonical_episode_id] = episode
        return episode

    def _selected_row(self) -> EpisodeExplorerDisplayRow | None:
        option_list = self.query_one("#episode-explorer-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        if highlighted < 0 or highlighted >= len(self._visible_rows):
            return None
        return self._visible_rows[highlighted]

    def _selected_display_episode_id(self) -> str | None:
        row = self._selected_row_or_none()
        return row.display_episode_id if row is not None else None

    def _selected_row_or_none(self) -> EpisodeExplorerDisplayRow | None:
        try:
            return self._selected_row()
        except Exception:
            return None

    def _current_source(
        self,
        *,
        episode: EpisodeWire | None = None,
    ) -> EpisodeSourceRefWire | None:
        row = self._selected_row()
        if row is None:
            return None
        if episode is None:
            episode = self._load_episode_for_row(row)
        if episode is None:
            return None
        sources = [source for source in episode.sources if source.path]
        if not sources:
            return None
        index = self._source_index.get(episode.episode_id, 0) % len(sources)
        self._source_index[episode.episode_id] = index
        return sources[index]

    def _step_source(self, step: int) -> None:
        row = self._selected_row()
        if row is None:
            return
        episode = self._load_episode_for_row(row)
        if episode is None:
            return
        sources = [source for source in episode.sources if source.path]
        if not sources:
            return
        current = self._source_index.get(episode.episode_id, 0)
        self._source_index[episode.episode_id] = (current + step) % len(sources)
        if self._view != "sources":
            self._view = "sources"
            self._refresh_static_chrome()
        self._render_selected_detail()

    def _refresh_static_chrome(self) -> None:
        self.query_one("#episode-explorer-title", Label).update(self._title_text())
        self.query_one("#episode-explorer-filter-summary", Static).update(
            self._filter_summary()
        )
        self.query_one("#episode-explorer-tabs", Static).update(self._tabs_text())
        self.query_one("#episode-explorer-hints", Static).update(self._hints_text())

    def _sync_filter_inputs(self) -> None:
        values = {
            "episode-filter-query": self._filters.query,
            "episode-filter-agent": self._filters.agent,
            "episode-filter-changespec": self._filters.changespec,
            "episode-filter-bead": self._filters.bead,
        }
        for widget_id, value in values.items():
            try:
                input_widget = self.query_one(f"#{widget_id}", Input)
                if input_widget.value != value:
                    input_widget.value = value
            except Exception:
                continue

    def _title_text(self) -> str:
        status = "loading" if self._loading else f"{len(self._visible_rows)} shown"
        return f"Episode Explorer - {self._project} [{status}]"

    def _filter_summary(self) -> str:
        since, until = range_bounds(self._filters.quick_range, today=self._today)
        range_text = str(self._filters.quick_range)
        if since or until:
            range_text += f" ({since or '-'}..{until or '-'})"
        parts = [
            f"range={range_text}",
            f"band={self._filters.band}",
            f"status={self._filters.status}",
            f"loaded={len(self._items)}",
        ]
        if self._filters.query.strip():
            parts.append(f"text={self._filters.query.strip()}")
        if self._filters.agent.strip():
            parts.append(f"agent={self._filters.agent.strip()}")
        if self._filters.changespec.strip():
            parts.append(f"changespec={self._filters.changespec.strip()}")
        if self._filters.bead.strip():
            parts.append(f"bead={self._filters.bead.strip()}")
        if self._error:
            parts.append("error")
        return "  ".join(parts)

    def _tabs_text(self) -> str:
        labels = []
        for index, view in enumerate(VIEWS, 1):
            label = f"{index}:{view}"
            labels.append(f"[{label}]" if view == self._view else label)
        return "  ".join(labels)

    def _hints_text(self) -> str:
        return (
            "r range  b band  s status  1-5 views  e edges  "
            "o open source  y copy id  g canonical  v verify  "
            "^r refresh  ^e inventory"
        )


__all__ = [
    "EpisodeExplorerStateMixin",
]
