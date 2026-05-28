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

from ..actions.clipboard import copy_to_system_clipboard
from .base import OptionListNavigationMixin


_SELECTOR_KEYS = "1234567890abcdefghijklmnopqrstuvwxyz"
_RESERVED_KEYS = {"j", "k", "m", "q", "y"}
_MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
_MAX_LABEL_LEN = 54
_MAX_AGENT_LABEL_LEN = 28
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


def _artifact_display_path(artifact: Any) -> str:
    source_path = str(getattr(artifact, "source_path", "") or "")
    if getattr(artifact, "kind", None) == "pdf" and source_path:
        return source_path
    return _artifact_path(artifact)


def _artifact_workspace_dir(artifact: Any) -> str | None:
    workspace_dir = getattr(artifact, "workspace_dir", None)
    return workspace_dir if isinstance(workspace_dir, str) and workspace_dir else None


def _artifact_resolved_display_path(artifact: Any) -> Path | None:
    path_text = _artifact_display_path(artifact)
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        workspace_dir = _artifact_workspace_dir(artifact)
        if workspace_dir:
            path = Path(workspace_dir).expanduser() / path
    return path


def _clipboard_path(path: Path) -> str:
    return _home_relative_path(path.expanduser().resolve(strict=False))


def _is_markdown_path(path: Path) -> bool:
    return path.suffix.lower() in _MARKDOWN_SUFFIXES


def _artifact_kind(artifact: Any) -> str:
    return _short_text(
        getattr(artifact, "kind", "file") or "file", max_len=_MAX_KIND_LEN
    )


def _artifact_label(artifact: Any, *, max_len: int = _MAX_LABEL_LEN) -> str:
    path = _artifact_path(artifact)
    fallback = Path(path).name if path else _artifact_kind(artifact)
    return _short_text(
        getattr(artifact, "label", None) or fallback,
        max_len=max_len,
    )


def _display_path(path: str, *, workspace_dir: str | None = None) -> str:
    if not path:
        return "(no path)"
    expanded = Path(path).expanduser()
    if workspace_dir:
        try:
            relative = expanded.resolve(strict=False).relative_to(
                Path(workspace_dir).expanduser().resolve(strict=False)
            )
        except (OSError, ValueError):
            pass
        else:
            return relative.as_posix() or "."
    return _home_relative_path(expanded)


def _home_relative_path(path: Path) -> str:
    try:
        relative = path.resolve(strict=False).relative_to(
            Path.home().expanduser().resolve(strict=False)
        )
    except (OSError, ValueError):
        return str(path)
    text = relative.as_posix()
    return "~" if not text else f"~/{text}"


def _short_path(
    path: str,
    *,
    max_len: int = _MAX_PATH_LEN,
    workspace_dir: str | None = None,
) -> str:
    return _short_text(
        _display_path(path, workspace_dir=workspace_dir),
        max_len=max_len,
        from_end=True,
    )


def _artifact_option_text(
    selector: str | None,
    artifact: Any,
    *,
    marked: bool = False,
    agent_label: str | None = None,
) -> Text:
    text = Text()
    if selector is None:
        text.append("   ", style="dim")
    else:
        text.append(f"{selector}  ", style="bold #D7AF5F")
    marker = "[x] " if marked else "    "
    marker_style = "bold #A6E3A1" if marked else "dim"
    text.append(marker, style=marker_style)
    label_budget = _MAX_LABEL_LEN
    if agent_label:
        prefix = _short_text(agent_label, max_len=_MAX_AGENT_LABEL_LEN)
        text.append(prefix, style="bold #87D7FF")
        text.append("  ·  ", style="dim")
        label_budget = max(16, _MAX_LABEL_LEN - len(prefix) - 5)
    text.append(_artifact_label(artifact, max_len=label_budget))
    text.append(f"  [{_artifact_kind(artifact)}]", style="dim #87D7FF")
    text.append("\n")
    display_path = _short_path(
        _artifact_display_path(artifact),
        workspace_dir=_artifact_workspace_dir(artifact),
    )
    text.append(f"   {display_path}", style="dim")
    return text


class AgentArtifactSelectionModal(
    OptionListNavigationMixin,
    ModalScreen[Any],
):
    """Keyboard-first artifact picker for the selected agent."""

    _option_list_id = "agent-artifacts-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("m", "toggle_mark", "Mark"),
        ("A", "open_all", "Open All"),
        ("y", "copy_contents", "Copy"),
        ("Y", "copy_path", "Copy path"),
        ("enter", "open_selected", "Open"),
    ]

    def __init__(
        self,
        artifacts: list[Any],
        *,
        agent_labels: list[str | None] | None = None,
        agent_count: int = 1,
    ) -> None:
        super().__init__()
        self._artifacts = artifacts
        if agent_labels is not None and len(agent_labels) != len(artifacts):
            raise ValueError("agent_labels must align with artifacts")
        self._agent_labels = agent_labels
        self._agent_count = max(1, agent_count)
        selectors = _artifact_selector_keys(len(artifacts))
        self._selector_by_index = selectors
        self._index_by_selector = {key: index for index, key in enumerate(selectors)}
        self._marked_indexes: set[int] = set()

    def compose(self) -> ComposeResult:
        with Container(id="agent-artifacts-container"):
            yield Label(
                self._title_text(),
                id="agent-artifacts-title",
            )
            yield OptionList(*self._create_options(), id=self._option_list_id)
            yield Static(
                self._hint_text(),
                id="agent-artifacts-hints",
            )

    def _title_text(self) -> str:
        if self._agent_count > 1:
            return (
                f"Agent Artifacts  [{len(self._artifacts)} from "
                f"{self._agent_count} agents]"
            )
        return f"Agent Artifacts  [{len(self._artifacts)}]"

    def _agent_label_for(self, index: int) -> str | None:
        if self._agent_labels is None:
            return None
        if index < 0 or index >= len(self._agent_labels):
            return None
        return self._agent_labels[index]

    def _create_options(self) -> list[Option]:
        options: list[Option] = []
        for index, artifact in enumerate(self._artifacts):
            selector = (
                self._selector_by_index[index]
                if index < len(self._selector_by_index)
                else None
            )
            options.append(
                Option(
                    _artifact_option_text(
                        selector,
                        artifact,
                        marked=index in self._marked_indexes,
                        agent_label=self._agent_label_for(index),
                    )
                )
            )
        return options

    def on_mount(self) -> None:
        self.query_one(f"#{self._option_list_id}", OptionList).focus()

    def on_key(self, event: events.Key) -> None:
        if event.key in self._index_by_selector:
            self.dismiss(self._artifacts[self._index_by_selector[event.key]])
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
        option_list.highlighted = (index + 1) % len(self._artifacts)
        self._update_hints()

    def action_open_selected(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        if self._marked_indexes:
            self.dismiss(
                [
                    artifact
                    for artifact_index, artifact in enumerate(self._artifacts)
                    if artifact_index in self._marked_indexes
                ]
            )
            return
        self.dismiss(self._artifacts[index])

    def action_copy_contents(self) -> None:
        """Copy the highlighted Markdown artifact contents."""
        artifact = self._selected_artifact()
        if artifact is None:
            self.notify("No artifact selected", severity="warning")
            return

        path = _artifact_resolved_display_path(artifact)
        if path is None:
            self.notify("Selected artifact has no path", severity="warning")
            return
        if not _is_markdown_path(path):
            self.notify("Selected artifact is not Markdown", severity="warning")
            return

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.notify(f"Failed to read artifact: {exc}", severity="error")
            return

        if copy_to_system_clipboard(content):
            line_count = len(content.splitlines()) if content else 0
            label = _artifact_label(artifact)
            self.notify(f"Copied: {label} ({line_count} lines)")
        else:
            self.notify("Failed to copy to clipboard", severity="error")

    def action_copy_path(self) -> None:
        """Copy the highlighted artifact display path."""
        artifact = self._selected_artifact()
        if artifact is None:
            self.notify("No artifact selected", severity="warning")
            return

        path = _artifact_resolved_display_path(artifact)
        if path is None:
            self.notify("Selected artifact has no path", severity="warning")
            return

        copy_path = _clipboard_path(path)
        if copy_to_system_clipboard(copy_path):
            self.notify(f"Copied: {copy_path}")
        else:
            self.notify("Failed to copy to clipboard", severity="error")

    def action_open_all(self) -> None:
        self.dismiss(list(self._artifacts))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_open_selected()

    def _selected_index(self) -> int | None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        index = option_list.highlighted
        if index is None or not 0 <= index < len(self._artifacts):
            return None
        return index

    def _selected_artifact(self) -> Any | None:
        index = self._selected_index()
        if index is None:
            return None
        return self._artifacts[index]

    def _refresh_option(self, index: int) -> None:
        selector = (
            self._selector_by_index[index]
            if index < len(self._selector_by_index)
            else None
        )
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        option_list.replace_option_prompt_at_index(
            index,
            _artifact_option_text(
                selector,
                self._artifacts[index],
                marked=index in self._marked_indexes,
                agent_label=self._agent_label_for(index),
            ),
        )
        option_list.highlighted = index

    def _hint_text(self) -> str:
        base = (
            "key/enter: open  y: copy  Y: path  m: mark  "
            "A: open all  j/k: navigate  q/esc: close"
        )
        mark_count = len(self._marked_indexes)
        if mark_count:
            return f"{base}  marked: {mark_count}"
        return base

    def _update_hints(self) -> None:
        self.query_one("#agent-artifacts-hints", Static).update(self._hint_text())
