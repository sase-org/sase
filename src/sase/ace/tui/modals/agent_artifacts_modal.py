"""Modal for choosing one artifact attached to an agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from .base import OptionListNavigationMixin


_SELECTOR_KEYS = "1234567890abcdefghijklmnopqrstuvwxyz"
_RESERVED_KEYS = {"j", "k", "q"}
_MAX_LABEL_LEN = 54
_MAX_KIND_LEN = 18
_MAX_PATH_LEN = 72


def _artifact_selector_keys(count: int) -> list[str]:
    keys = [key for key in _SELECTOR_KEYS if key not in _RESERVED_KEYS]
    return keys[:count]


def _short_text(value: object, *, max_len: int, from_end: bool = False) -> str:
    text = str(value or "")
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    if from_end:
        return "..." + text[-(max_len - 3) :]
    return text[: max_len - 3] + "..."


def _artifact_path(artifact: Any) -> str:
    return str(getattr(artifact, "path", "") or "")


def _artifact_kind(artifact: Any) -> str:
    return _short_text(
        getattr(artifact, "kind", "file") or "file", max_len=_MAX_KIND_LEN
    )


def _artifact_label(artifact: Any) -> str:
    path = _artifact_path(artifact)
    fallback = Path(path).name if path else _artifact_kind(artifact)
    return _short_text(
        getattr(artifact, "label", None) or fallback,
        max_len=_MAX_LABEL_LEN,
    )


def _short_path(path: str, *, max_len: int = _MAX_PATH_LEN) -> str:
    if not path:
        return "(no path)"
    expanded = str(Path(path).expanduser())
    return _short_text(expanded, max_len=max_len, from_end=True)


def _artifact_option_text(selector: str | None, artifact: Any) -> Text:
    text = Text()
    if selector is None:
        text.append("   ", style="dim")
    else:
        text.append(f"{selector}  ", style="bold #D7AF5F")
    text.append(_artifact_label(artifact))
    text.append(f"  [{_artifact_kind(artifact)}]", style="dim #87D7FF")
    text.append("\n")
    text.append(f"   {_short_path(_artifact_path(artifact))}", style="dim")
    return text


class AgentArtifactSelectionModal(
    OptionListNavigationMixin,
    ModalScreen[Any],
):
    """Keyboard-first artifact picker for the selected agent."""

    _option_list_id = "agent-artifacts-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "open_selected", "Open"),
    ]

    def __init__(self, artifacts: list[Any]) -> None:
        super().__init__()
        self._artifacts = artifacts
        selectors = _artifact_selector_keys(len(artifacts))
        self._selector_by_index = selectors
        self._index_by_selector = {key: index for index, key in enumerate(selectors)}

    def compose(self) -> ComposeResult:
        with Container(id="agent-artifacts-container"):
            yield Label(
                f"Agent Artifacts  [{len(self._artifacts)}]",
                id="agent-artifacts-title",
            )
            yield OptionList(*self._create_options(), id=self._option_list_id)
            yield Static(
                "key/enter: open  j/k: navigate  q/esc: close",
                id="agent-artifacts-hints",
            )

    def _create_options(self) -> list[Option]:
        options: list[Option] = []
        for index, artifact in enumerate(self._artifacts):
            selector = (
                self._selector_by_index[index]
                if index < len(self._selector_by_index)
                else None
            )
            options.append(Option(_artifact_option_text(selector, artifact)))
        return options

    def on_mount(self) -> None:
        self.query_one(f"#{self._option_list_id}", OptionList).focus()

    def on_key(self, event: events.Key) -> None:
        if event.key in self._index_by_selector:
            self.dismiss(self._artifacts[self._index_by_selector[event.key]])
            event.prevent_default()
            event.stop()

    def action_open_selected(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        index = option_list.highlighted
        if index is None or not 0 <= index < len(self._artifacts):
            return
        self.dismiss(self._artifacts[index])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_open_selected()
