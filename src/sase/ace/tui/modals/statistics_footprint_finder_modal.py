"""Filterable feature finder for the Statistics Footprint view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from .base import FilterInput, OptionListNavigationMixin


class _StatisticsFootprintFinderInput(FilterInput):
    """Filter input that reserves picker navigation and cancel keys."""

    async def _on_key(self, event: events.Key) -> None:
        modal = self.screen
        if isinstance(modal, StatisticsFootprintFinderModal):
            action = {
                "j": modal.action_next_option,
                "down": modal.action_next_option,
                "ctrl+n": modal.action_next_option,
                "k": modal.action_prev_option,
                "up": modal.action_prev_option,
                "ctrl+p": modal.action_prev_option,
                "escape": modal.action_cancel,
                "q": modal.action_cancel,
            }.get(event.key)
            if action is not None:
                event.prevent_default()
                event.stop()
                action()
                return
        await super()._on_key(event)


@dataclass(frozen=True)
class FootprintFeatureChoice:
    """A chosen catalog feature; ``None`` feature_id means no selection."""

    feature_id: str | None
    area: str | None = None


@dataclass(frozen=True)
class FinderFeature:
    """One catalog feature shown by the finder."""

    feature_id: str
    label: str
    area: str
    kind: str


def catalog_features() -> tuple[FinderFeature, ...]:
    """Return every catalog feature sorted by label for the finder."""
    from sase.footprint.catalog import load_catalog

    _header, entries = load_catalog()
    features = tuple(
        FinderFeature(
            feature_id=entry.id,
            label=entry.label,
            area=entry.area,
            kind=entry.kind,
        )
        for entry in entries
    )
    return tuple(
        sorted(features, key=lambda item: (item.label.casefold(), item.feature_id))
    )


class StatisticsFootprintFinderModal(
    OptionListNavigationMixin,
    ModalScreen[FootprintFeatureChoice | None],
):
    """Choose one catalog feature without reading the usage ledger."""

    _option_list_id = "statistics-footprint-finder-list"
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        *OptionListNavigationMixin.NAVIGATION_BINDINGS[2:],
        ("enter", "select_highlighted", "Apply"),
    ]

    def __init__(
        self,
        features: tuple[FinderFeature, ...],
        *,
        current_feature_id: str | None = None,
    ) -> None:
        super().__init__()
        self._features = features
        self._filtered = list(features)
        self._current_feature_id = current_feature_id

    def compose(self) -> ComposeResult:
        from textual.containers import Container

        with Container(id="statistics-footprint-finder-container"):
            yield Static(self._title_text(), id="statistics-footprint-finder-title")
            yield _StatisticsFootprintFinderInput(
                placeholder="Type to filter features…",
                id="statistics-footprint-finder-filter",
            )
            yield OptionList(
                *self._create_options(self._filtered),
                id=self._option_list_id,
            )
            yield Static(
                "Enter open · j/k or ↑/↓ move · q/Esc cancel",
                id="statistics-footprint-finder-hints",
            )

    def on_mount(self) -> None:
        options = self.query_one(f"#{self._option_list_id}", OptionList)
        preferred_index = 0
        if self._current_feature_id is not None:
            for index, feature in enumerate(self._filtered):
                if feature.feature_id == self._current_feature_id:
                    preferred_index = index
                    break
        options.highlighted = preferred_index
        self.query_one(
            "#statistics-footprint-finder-filter",
            _StatisticsFootprintFinderInput,
        ).focus()

    def _title_text(self) -> Text:
        text = Text()
        text.append("✦ ", style="bold #FF87D7")
        text.append("Find Feature", style="bold")
        text.append("  ·  ", style="dim")
        text.append(f"{len(self._filtered)} features", style="dim")
        return text

    @staticmethod
    def _row_label(feature: FinderFeature) -> Text:
        text = Text()
        text.append(f"{feature.label:<28.28}", style="bold #87D7FF")
        text.append(f"{feature.area:<18.18}", style="#C6A0F6")
        text.append(feature.feature_id, style="dim")
        return text

    def _create_options(self, features: list[FinderFeature]) -> list[Option]:
        return [
            Option(self._row_label(feature), id=feature.feature_id)
            for feature in features
        ]

    def _matches(self, feature: FinderFeature, needle: str) -> bool:
        if not needle:
            return True
        folded = needle.casefold()
        return (
            folded in feature.label.casefold()
            or folded in feature.feature_id.casefold()
        )

    def _apply_filter(self, value: str) -> None:
        needle = value.strip()
        self._filtered = [
            feature for feature in self._features if self._matches(feature, needle)
        ]
        options = self.query_one(f"#{self._option_list_id}", OptionList)
        options.clear_options()
        for option in self._create_options(self._filtered):
            options.add_option(option)
        options.highlighted = 0
        self.query_one("#statistics-footprint-finder-title", Static).update(
            self._title_text()
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "statistics-footprint-finder-filter":
            self._apply_filter(event.value)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.action_select_highlighted()

    def on_key(self, event: events.Key) -> None:
        """Keep list navigation available while the filter owns focus."""
        if event.key in ("escape", "q"):
            event.prevent_default()
            event.stop()
            self.action_cancel()
        elif event.key in ("down", "ctrl+n", "j"):
            event.prevent_default()
            event.stop()
            self.action_next_option()
        elif event.key in ("up", "ctrl+p", "k"):
            event.prevent_default()
            event.stop()
            self.action_prev_option()

    def on_option_list_option_selected(
        self,
        _event: OptionList.OptionSelected,
    ) -> None:
        self.action_select_highlighted()

    def action_select_highlighted(self) -> None:
        options = self.query_one(f"#{self._option_list_id}", OptionList)
        highlighted = options.highlighted
        if highlighted is None:
            return
        if 0 <= highlighted < len(self._filtered):
            feature = self._filtered[highlighted]
            self.dismiss(
                FootprintFeatureChoice(feature_id=feature.feature_id, area=feature.area)
            )

    def _finder_state(self) -> dict[str, Any]:
        """Expose filtered rows for tests without reaching into widgets."""
        return {
            "total": len(self._features),
            "filtered": [item.feature_id for item in self._filtered],
        }


__all__ = [
    "FinderFeature",
    "FootprintFeatureChoice",
    "StatisticsFootprintFinderModal",
    "catalog_features",
]
