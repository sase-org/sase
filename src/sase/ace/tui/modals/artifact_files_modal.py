"""Modal for choosing one artifact file attached to an agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.keymaps import footer_key_display

from .artifact_files_modal_copying import ArtifactFileCopyingMixin
from .artifact_files_modal_rendering import (
    artifact_file_option_text as _artifact_file_option_text,
    artifact_file_selector_keys as _artifact_file_selector_keys,
)
from .base import OptionListNavigationMixin


@dataclass(frozen=True)
class ArtifactFileSelectionResult:
    """Explicit modal result for actions that carry open options."""

    artifact_files: list[Any]
    zoom: bool = False


class ArtifactFileSelectionModal(
    ArtifactFileCopyingMixin,
    OptionListNavigationMixin,
    ModalScreen[Any],
):
    """Keyboard-first artifact-file picker for the selected agent."""

    _option_list_id = "agent-artifact-files-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("m", "toggle_mark", "Mark"),
        ("A", "open_all", "Open All"),
        ("z", "zoom_open", "Zoom Open"),
        ("y", "copy_contents", "Copy"),
        ("Y", "copy_path", "Copy path"),
        ("enter", "open_selected", "Open"),
    ]

    def __init__(
        self,
        artifact_files: list[Any],
        *,
        agent_labels: list[str | None] | None = None,
        agent_count: int = 1,
    ) -> None:
        super().__init__()
        self._artifact_files = artifact_files
        if agent_labels is not None and len(agent_labels) != len(artifact_files):
            raise ValueError("agent_labels must align with artifact files")
        self._agent_labels = agent_labels
        self._agent_count = max(1, agent_count)
        selectors = _artifact_file_selector_keys(len(artifact_files))
        self._selector_by_index = selectors
        self._index_by_selector = {key: index for index, key in enumerate(selectors)}
        self._marked_indexes: set[int] = set()

    def compose(self) -> ComposeResult:
        with Container(id="agent-artifact-files-container"):
            yield Label(
                self._title_text(),
                id="agent-artifact-files-title",
            )
            yield OptionList(*self._create_options(), id=self._option_list_id)
            yield Static(
                self._hint_text(),
                id="agent-artifact-files-hints",
            )

    def _title_text(self) -> str:
        if self._agent_count > 1:
            return (
                f"Artifact Files  [{len(self._artifact_files)} from "
                f"{self._agent_count} agents]"
            )
        return f"Artifact Files  [{len(self._artifact_files)}]"

    def _agent_label_for(self, index: int) -> str | None:
        if self._agent_labels is None:
            return None
        if index < 0 or index >= len(self._agent_labels):
            return None
        return self._agent_labels[index]

    def _create_options(self) -> list[Option]:
        options: list[Option] = []
        for index, artifact_file in enumerate(self._artifact_files):
            selector = (
                self._selector_by_index[index]
                if index < len(self._selector_by_index)
                else None
            )
            options.append(
                Option(
                    _artifact_file_option_text(
                        selector,
                        artifact_file,
                        marked=index in self._marked_indexes,
                        agent_label=self._agent_label_for(index),
                    )
                )
            )
        return options

    def on_mount(self) -> None:
        self.query_one(f"#{self._option_list_id}", OptionList).focus()

    def on_key(self, event: events.Key) -> None:
        copy_prefix = self._copy_prefix()
        if event.key == copy_prefix or event.character == copy_prefix:
            self.action_open_copy_as()
            event.prevent_default()
            event.stop()
            return
        if event.key in self._index_by_selector:
            self.dismiss(self._artifact_files[self._index_by_selector[event.key]])
            event.prevent_default()
            event.stop()

    def action_toggle_mark(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        if index in self._marked_indexes:
            self._marked_indexes.remove(index)
        else:
            self._marked_indexes.add(index)
        self._refresh_option(index)
        option_list.highlighted = (index + 1) % len(self._artifact_files)
        self._update_hints()

    def action_open_selected(self) -> None:
        artifact_files = self._selected_artifact_files()
        if artifact_files is None:
            return
        if self._marked_indexes:
            self.dismiss(artifact_files)
            return
        self.dismiss(artifact_files[0])

    def action_zoom_open(self) -> None:
        artifact_files = self._selected_artifact_files()
        if artifact_files is None:
            return
        self.dismiss(ArtifactFileSelectionResult(artifact_files, zoom=True))

    def _selected_artifact_files(self) -> list[Any] | None:
        index = self._selected_index()
        if index is None:
            return None
        if self._marked_indexes:
            return [
                artifact_file
                for artifact_index, artifact_file in enumerate(self._artifact_files)
                if artifact_index in self._marked_indexes
            ]
        return [self._artifact_files[index]]

    def action_open_all(self) -> None:
        self.dismiss(list(self._artifact_files))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_open_selected()

    def _selected_index(self) -> int | None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        index = option_list.highlighted
        if index is None or not 0 <= index < len(self._artifact_files):
            return None
        return index

    def _selected_artifact_file(self) -> Any | None:
        index = self._selected_index()
        if index is None:
            return None
        return self._artifact_files[index]

    def _refresh_option(self, index: int) -> None:
        selector = (
            self._selector_by_index[index]
            if index < len(self._selector_by_index)
            else None
        )
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        option_list.replace_option_prompt_at_index(
            index,
            _artifact_file_option_text(
                selector,
                self._artifact_files[index],
                marked=index in self._marked_indexes,
                agent_label=self._agent_label_for(index),
            ),
        )
        option_list.highlighted = index

    def _hint_text(self) -> str:
        base = (
            f"key/enter: open  {footer_key_display(self._copy_prefix())}: Copy as…  "
            "z: zoom open  y: copy  Y: path  m: mark  "
            "A: open all  j/k: navigate  q/esc: close"
        )
        mark_count = len(self._marked_indexes)
        if mark_count:
            return f"{base}  marked: {mark_count}"
        return base

    def _update_hints(self) -> None:
        self.query_one("#agent-artifact-files-hints", Static).update(self._hint_text())
