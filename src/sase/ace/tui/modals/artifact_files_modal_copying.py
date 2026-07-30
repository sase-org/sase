"""Clipboard and Copy-as behavior for the artifact-file selection modal."""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import TYPE_CHECKING, Any

from sase.ace.tui.actions.clipboard._helpers import (
    cap_copy_content,
    format_markdown_link,
    format_multi_copy_content_capped,
)
from sase.ace.tui.keymaps import footer_key_display
from sase.artifact_cli.references import artifact_file_json_dict

from ..actions.clipboard import schedule_copy_delivery
from ..models.artifact_file_clipboard import (
    ArtifactFilePathCopy,
    artifact_file_clipboard_path,
    artifact_file_source_clipboard_path,
)
from .artifact_files_modal_rendering import (
    artifact_file_is_markdown,
    artifact_file_label,
    artifact_file_path,
    artifact_file_reference,
    artifact_file_resolved_display_path,
    artifact_file_stored_clipboard_path,
)
from .copy_as_modal import CopyAsModal
from .copy_as_types import CopyAsContext, CopyAsRow

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class ArtifactFileCopyingMixin(_MixinBase):
    """Provide clipboard actions for the artifact-file picker."""

    if TYPE_CHECKING:
        _artifact_files: list[Any]
        _marked_indexes: set[int]

        def _selected_artifact_files(self) -> list[Any] | None: ...

    def action_copy_contents(self) -> None:
        """Copy selected Markdown contents; marks use a bounded fenced set."""
        artifact_files = self._selected_artifact_files()
        if artifact_files is None:
            self.notify("No artifact file selected", severity="warning")
            return

        markdown_files = [
            artifact_file
            for artifact_file in artifact_files
            if artifact_file_is_markdown(artifact_file)
        ]
        if not markdown_files:
            self.notify("Selected artifact file is not Markdown", severity="warning")
            return
        self._schedule_file_copy(
            artifact_files,
            resolve_one=self._read_artifact_file_contents,
            format_marked=lambda values: format_multi_copy_content_capped(values),
            singular_label=lambda artifact_file, value: (
                f"{artifact_file_label(artifact_file)} "
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
            artifact_file_is_markdown(artifact_file) for artifact_file in artifact_files
        )
        stored_count = sum(
            bool(artifact_file_path(artifact_file)) for artifact_file in artifact_files
        )
        source_count = sum(
            bool(getattr(artifact_file, "source_path", None))
            for artifact_file in artifact_files
        )
        subtitle = (
            f"{count} marked artifact files" if marked else artifact_file_label(first)
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
                resolve_one=lambda artifact_file: artifact_file_reference(
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
                    artifact_file_label(artifact_file),
                    artifact_file_reference(artifact_file, prompt_form=False),
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
                resolver=artifact_file_stored_clipboard_path,
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
        if not artifact_file_is_markdown(artifact_file):
            raise ValueError("artifact file is not Markdown")
        path = artifact_file_resolved_display_path(artifact_file)
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
                resolved_values.append((artifact_file_label(artifact_file), resolved))
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
