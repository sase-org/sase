"""Modal for choosing one artifact file attached to an agent."""

from __future__ import annotations

from collections.abc import Callable
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.actions.clipboard._helpers import (
    cap_copy_content,
    format_markdown_link,
    format_multi_copy_content_capped,
)
from sase.ace.tui.keymaps import footer_key_display
from sase.artifact_cli.references import artifact_file_json_dict

from sase.ace.tui.graphics import is_supported_video_path

from ..actions.clipboard import schedule_copy_delivery
from ..models.artifact_file_clipboard import (
    ArtifactFilePathCopy,
    artifact_file_clipboard_path,
    artifact_file_clipboard_workspace_dir,
    artifact_file_preferred_path_text,
    artifact_file_resolved_stored_path,
    artifact_file_source_clipboard_path,
)
from .base import OptionListNavigationMixin
from .copy_as_modal import CopyAsModal
from .copy_as_types import CopyAsContext, CopyAsRow


_SELECTOR_KEYS = "1234567890abcdefghijklmnopqrstuvwxyz"
_RESERVED_KEYS = {"j", "k", "m", "q", "y", "Y", "z"}
_MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
_MAX_LABEL_LEN = 54
_MAX_AGENT_LABEL_LEN = 28
_MAX_KIND_LEN = 18
_MAX_PATH_LEN = 72


def _artifact_file_selector_keys(count: int) -> list[str]:
    keys = [key for key in _SELECTOR_KEYS if key not in _RESERVED_KEYS]
    return keys[:count]


@dataclass(frozen=True)
class ArtifactFileSelectionResult:
    """Explicit modal result for actions that carry open options."""

    artifact_files: list[Any]
    zoom: bool = False


def _short_text(value: object, *, max_len: int, from_end: bool = False) -> str:
    text = str(value or "")
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    if from_end:
        return "..." + text[-(max_len - 3) :]
    return text[: max_len - 3] + "..."


def _artifact_file_path(artifact_file: Any) -> str:
    return str(getattr(artifact_file, "path", "") or "")


def _artifact_file_display_path(artifact_file: Any) -> str:
    return artifact_file_preferred_path_text(artifact_file)[0]


def _artifact_file_workspace_dir(artifact_file: Any) -> str | None:
    workspace_dir = getattr(artifact_file, "workspace_dir", None)
    return workspace_dir if isinstance(workspace_dir, str) and workspace_dir else None


def _artifact_file_resolved_display_path(artifact_file: Any) -> Path | None:
    path_text = _artifact_file_display_path(artifact_file)
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        workspace_dir = artifact_file_clipboard_workspace_dir(artifact_file)
        if workspace_dir:
            path = Path(workspace_dir).expanduser() / path
    return path


def _is_markdown_path(path: Path) -> bool:
    return path.suffix.lower() in _MARKDOWN_SUFFIXES


def _artifact_file_is_markdown(artifact_file: Any) -> bool:
    path = _artifact_file_display_path(artifact_file)
    return bool(path and _is_markdown_path(Path(path)))


def _artifact_file_reference(artifact_file: Any, *, prompt_form: bool) -> str:
    artifact_id = str(getattr(artifact_file, "id", "") or "")
    if not artifact_id:
        raise ValueError("artifact file has no durable reference")
    prefix = "@" if prompt_form else ""
    return f"{prefix}file:{artifact_id}"


def _artifact_file_kind(artifact_file: Any) -> str:
    if is_supported_video_path(_artifact_file_display_path(artifact_file)):
        return "video"
    return _short_text(
        getattr(artifact_file, "kind", "file") or "file", max_len=_MAX_KIND_LEN
    )


def _artifact_file_label(artifact_file: Any, *, max_len: int = _MAX_LABEL_LEN) -> str:
    path = _artifact_file_path(artifact_file)
    fallback = Path(path).name if path else _artifact_file_kind(artifact_file)
    return _short_text(
        getattr(artifact_file, "label", None) or fallback,
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


def _artifact_file_stored_clipboard_path(
    artifact_file: Any,
) -> ArtifactFilePathCopy | None:
    path = artifact_file_resolved_stored_path(artifact_file)
    if path is None:
        return None
    return ArtifactFilePathCopy(_home_relative_path(path), "stored")


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


def _artifact_file_option_text(
    selector: str | None,
    artifact_file: Any,
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
    text.append(_artifact_file_label(artifact_file, max_len=label_budget))
    text.append(f"  [{_artifact_file_kind(artifact_file)}]", style="dim #87D7FF")
    text.append("\n")
    display_path = _short_path(
        _artifact_file_display_path(artifact_file),
        workspace_dir=_artifact_file_workspace_dir(artifact_file),
    )
    text.append(f"   {display_path}", style="dim")
    return text


class ArtifactFileSelectionModal(
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

    def action_copy_contents(self) -> None:
        """Copy selected Markdown contents; marks use a bounded fenced set."""
        artifact_files = self._selected_artifact_files()
        if artifact_files is None:
            self.notify("No artifact file selected", severity="warning")
            return

        markdown_files = [
            artifact_file
            for artifact_file in artifact_files
            if _artifact_file_is_markdown(artifact_file)
        ]
        if not markdown_files:
            self.notify("Selected artifact file is not Markdown", severity="warning")
            return
        self._schedule_file_copy(
            artifact_files,
            resolve_one=self._read_artifact_file_contents,
            format_marked=lambda values: format_multi_copy_content_capped(values),
            singular_label=lambda artifact_file, value: (
                f"{_artifact_file_label(artifact_file)} "
                f"({len(value.splitlines()) if value else 0} lines)"
            ),
            singular_noun="artifact file's contents",
            plural_noun="artifact file contents",
            unavailable_noun="non-Markdown",
            task_name="sase-copy-artifact-file-contents",
        )

    def action_copy_path(self) -> None:
        """Copy the selected file's legacy stored-or-source anchored path."""
        artifact_files = self._selected_artifact_files()
        if artifact_files is None:
            self.notify("No artifact file selected", severity="warning")
            return
        self._copy_paths(
            artifact_files,
            resolver=artifact_file_clipboard_path,
            plural_noun="artifact file paths",
            unavailable_noun="without a path",
            task_name="sase-copy-artifact-file-path",
        )

    def action_open_copy_as(self) -> None:
        """Open the modal-local file representation palette."""
        artifact_files = self._selected_artifact_files()
        if artifact_files is None:
            self.notify("No artifact file selected", severity="warning")
            return
        context = self._copy_as_context(artifact_files)

        def on_dismiss(row: CopyAsRow | None) -> None:
            if row is None:
                return
            if row.captures_snapshot:

                def callback() -> None:
                    self._dispatch_copy_as_target(row.target)

                call_after_refresh = getattr(self.app, "call_after_refresh", None)
                if callable(call_after_refresh):
                    call_after_refresh(callback)
                else:
                    callback()
                return
            self._dispatch_copy_as_target(row.target)

        self.app.push_screen(CopyAsModal(context), callback=on_dismiss)

    def _copy_as_context(self, artifact_files: list[Any]) -> CopyAsContext:
        marked = bool(self._marked_indexes)
        count = len(artifact_files)
        first = artifact_files[0]
        reference_count = sum(
            bool(getattr(artifact_file, "id", None)) for artifact_file in artifact_files
        )
        markdown_count = sum(
            _artifact_file_is_markdown(artifact_file)
            for artifact_file in artifact_files
        )
        stored_count = sum(
            bool(_artifact_file_path(artifact_file)) for artifact_file in artifact_files
        )
        source_count = sum(
            bool(getattr(artifact_file, "source_path", None))
            for artifact_file in artifact_files
        )
        subtitle = (
            f"{count} marked artifact files" if marked else _artifact_file_label(first)
        )

        def marked_preview(available: int, noun: str) -> str:
            if not marked:
                return noun
            missing = count - available
            suffix = f" · {missing} unavailable" if missing else ""
            return f"{available} {noun}{suffix}"

        rows = (
            CopyAsRow(
                key="at",
                key_display=footer_key_display("at"),
                target="reference",
                label=(
                    "artifact file references"
                    if marked
                    else "Copy artifact file reference"
                ),
                category="Identity",
                preview=marked_preview(reference_count, "references"),
                disabled_reason=(
                    None
                    if reference_count
                    else "Artifact file has no durable reference"
                ),
            ),
            CopyAsRow(
                key="l",
                key_display=footer_key_display("l"),
                target="link",
                label="Markdown links" if marked else "Copy Markdown link",
                category="Location",
                preview=marked_preview(reference_count, "links"),
                disabled_reason=(
                    None
                    if reference_count
                    else "Artifact file has no durable reference"
                ),
            ),
            CopyAsRow(
                key="p",
                key_display=footer_key_display("p"),
                target="stored_path",
                label="stored paths" if marked else "Copy stored path",
                category="Location",
                preview=marked_preview(stored_count, "stored paths"),
                disabled_reason=(
                    None if stored_count else "Artifact file has no stored path"
                ),
            ),
            CopyAsRow(
                key="P",
                key_display=footer_key_display("P"),
                target="source_path",
                label="source paths" if marked else "Copy source path",
                category="Location",
                preview=(
                    marked_preview(source_count, "source paths")
                    if source_count
                    else "not recorded"
                ),
                disabled_reason=(
                    None
                    if source_count
                    else "Artifact file source path was not recorded"
                ),
            ),
            CopyAsRow(
                key="c",
                key_display=footer_key_display("c"),
                target="contents",
                label=(
                    "Markdown file contents" if marked else "Copy Markdown contents"
                ),
                category="Content",
                preview=(
                    marked_preview(markdown_count, "Markdown files")
                    if marked
                    else (
                        "Markdown contents"
                        if markdown_count
                        else "unavailable for non-Markdown files"
                    )
                ),
                disabled_reason=(
                    None
                    if markdown_count
                    else "Contents copy is available only for Markdown files"
                ),
            ),
            CopyAsRow(
                key="J",
                key_display=footer_key_display("J"),
                target="json",
                label="metadata JSON records" if marked else "Copy metadata JSON",
                category="Data",
                preview=f"{count} records" if marked else "artifact file metadata",
            ),
            CopyAsRow(
                key="s",
                key_display=footer_key_display("s"),
                target="snapshot",
                label="Copy snapshot",
                category="Actions",
                preview="artifact files modal",
            ),
        )
        return CopyAsContext(
            group="artifact_files_modal",
            subtitle=subtitle,
            unknown_context="artifact files",
            rows=rows,
        )

    def _dispatch_copy_as_target(self, target: str) -> None:
        artifact_files = self._selected_artifact_files()
        if artifact_files is None:
            self.notify("No artifact file selected", severity="warning")
            return
        if target == "reference":
            self._schedule_file_copy(
                artifact_files,
                resolve_one=lambda artifact_file: _artifact_file_reference(
                    artifact_file, prompt_form=True
                ),
                format_marked=lambda values: "\n".join(value for _, value in values),
                singular_label=lambda _artifact_file, _value: "artifact file reference",
                singular_noun="artifact file reference",
                plural_noun="artifact file references",
                unavailable_noun="without a reference",
                task_name="sase-copy-artifact-file-reference",
            )
        elif target == "link":
            self._schedule_file_copy(
                artifact_files,
                resolve_one=lambda artifact_file: format_markdown_link(
                    _artifact_file_label(artifact_file),
                    _artifact_file_reference(artifact_file, prompt_form=False),
                ),
                format_marked=lambda values: "\n".join(
                    f"- {value}" for _, value in values
                ),
                singular_label=lambda _artifact_file, _value: (
                    "artifact file Markdown link"
                ),
                singular_noun="artifact file Markdown link",
                plural_noun="artifact file Markdown links",
                unavailable_noun="without a reference",
                task_name="sase-copy-artifact-file-link",
            )
        elif target == "contents":
            self.action_copy_contents()
        elif target == "stored_path":
            self._copy_paths(
                artifact_files,
                resolver=_artifact_file_stored_clipboard_path,
                plural_noun="stored paths",
                unavailable_noun="without a stored path",
                task_name="sase-copy-artifact-file-stored-path",
            )
        elif target == "source_path":
            self._copy_paths(
                artifact_files,
                resolver=artifact_file_source_clipboard_path,
                plural_noun="source paths",
                unavailable_noun="without a recorded source path",
                task_name="sase-copy-artifact-file-source-path",
            )
        elif target == "json":
            self._schedule_file_copy(
                artifact_files,
                resolve_one=artifact_file_json_dict,
                format_single=lambda value: json.dumps(value, indent=2),
                format_marked=lambda values: json.dumps(
                    [value for _, value in values],
                    indent=2,
                ),
                singular_label=lambda _artifact_file, _value: (
                    "artifact file metadata JSON"
                ),
                singular_noun="artifact file metadata JSON record",
                plural_noun="artifact file metadata JSON records",
                unavailable_noun="with unavailable metadata",
                task_name="sase-copy-artifact-file-json",
            )
        elif target == "snapshot":
            copy_snapshot = getattr(self.app, "_copy_snapshot", None)
            if callable(copy_snapshot):
                copy_snapshot()
            else:
                self.notify("Snapshot copy is unavailable", severity="warning")

    def _copy_paths(
        self,
        artifact_files: list[Any],
        *,
        resolver: Callable[[Any], ArtifactFilePathCopy | None],
        plural_noun: str,
        unavailable_noun: str,
        task_name: str,
    ) -> None:
        path_state: dict[int, ArtifactFilePathCopy] = {}

        def resolve_one(artifact_file: Any) -> str:
            copy_path = resolver(artifact_file)
            if copy_path is None:
                raise ValueError("artifact file has no path")
            path_state[id(artifact_file)] = copy_path
            return copy_path.text

        def singular_label(artifact_file: Any, _value: Any) -> str:
            copy_path = path_state[id(artifact_file)]
            suffix = " (no longer exists)" if copy_path.missing else ""
            return f"{copy_path.label}{suffix}: {copy_path.text}"

        self._schedule_file_copy(
            artifact_files,
            resolve_one=resolve_one,
            format_marked=lambda values: "\n".join(value for _, value in values),
            singular_label=singular_label,
            singular_noun=plural_noun.removesuffix("s"),
            plural_noun=plural_noun,
            unavailable_noun=unavailable_noun,
            task_name=task_name,
        )

    @staticmethod
    def _read_artifact_file_contents(artifact_file: Any) -> str:
        if not _artifact_file_is_markdown(artifact_file):
            raise ValueError("artifact file is not Markdown")
        path = _artifact_file_resolved_display_path(artifact_file)
        if path is None:
            raise ValueError("artifact file has no path")
        return path.read_text(encoding="utf-8", errors="replace")

    def _schedule_file_copy(
        self,
        artifact_files: list[Any],
        *,
        resolve_one: Callable[[Any], Any],
        singular_label: Callable[[Any, Any], str],
        singular_noun: str,
        plural_noun: str,
        unavailable_noun: str,
        task_name: str,
        format_marked: Callable[[list[tuple[str, Any]]], Any],
        format_single: Callable[[Any], str] = str,
    ) -> None:
        marked = bool(self._marked_indexes)
        state = {"successes": 0, "failures": 0, "truncated": False}
        resolved_values: list[tuple[str, Any]] = []

        def value() -> str:
            failures = 0
            for artifact_file in artifact_files:
                try:
                    resolved = resolve_one(artifact_file)
                except Exception:
                    failures += 1
                    continue
                resolved_values.append((_artifact_file_label(artifact_file), resolved))
            if not resolved_values:
                raise ValueError(f"no selected artifact files are {unavailable_noun}")

            state["successes"] = len(resolved_values)
            state["failures"] = failures
            if marked:
                formatted = format_marked(resolved_values)
                if hasattr(formatted, "value") and hasattr(formatted, "truncated"):
                    state["truncated"] = bool(formatted.truncated)
                    return str(formatted.value)
                return str(formatted)

            formatted = format_single(resolved_values[0][1])
            if isinstance(formatted, str):
                capped = cap_copy_content(formatted)
                state["truncated"] = capped.truncated
                return capped.value
            return str(formatted)

        def copied_label() -> str:
            if not marked:
                label = singular_label(artifact_files[0], resolved_values[0][1])
            else:
                noun = singular_noun if state["successes"] == 1 else plural_noun
                label = f"{state['successes']} {noun}"
                if state["failures"]:
                    label += f" — {state['failures']} {unavailable_noun}"
            if state["truncated"]:
                label += " — truncated"
            return label

        schedule_copy_delivery(
            self,
            value,
            copied_label=copied_label,
            task_name=task_name,
        )

    def _copy_prefix(self) -> str:
        try:
            registry = getattr(self.app, "_keymap_registry", None)
        except Exception:
            registry = None
        copy_mode = getattr(registry, "copy_mode", None)
        prefix = getattr(copy_mode, "prefix", "%")
        return prefix if isinstance(prefix, str) and prefix else "%"

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
