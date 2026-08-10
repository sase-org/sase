"""Confirmation panel for saving a pane-scoped snippet draft."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
from pathlib import Path
from typing import Literal

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from sase.xprompt.snippet_config_yaml import generate_snippet_yaml

SnippetSaveConfirmResult = Literal["save", "close", "reload"]
SnippetSavePreviewTab = Literal["draft", "existing", "diff"]


@dataclass(frozen=True, slots=True)
class SnippetSaveConfirmState:
    """All disk-backed facts needed to confirm one snippet save."""

    trigger: str
    display_path: str
    body: str
    exists: bool
    existing_body: str | None
    changed_on_disk: bool = False
    warning: str | None = None


class SnippetSaveConfirmModal(
    ModalScreen[SnippetSaveConfirmResult | None],
):
    """Show the final diff before writing a snippet target pane."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "save", "Save", show=False),
        Binding("r", "reload_current", "Reload", show=False),
        Binding("ctrl+o", "cycle_preview", "Cycle preview", show=False),
        Binding("ctrl+d", "scroll_preview_down", "Scroll down", show=False),
        Binding("ctrl+u", "scroll_preview_up", "Scroll up", show=False),
    ]

    def __init__(self, state: SnippetSaveConfirmState) -> None:
        super().__init__()
        self._state = state
        self._preview_tab: SnippetSavePreviewTab = (
            "diff" if state.existing_body is not None else "draft"
        )

    def compose(self) -> ComposeResult:
        with Container(id="snippet-save-confirm-container"):
            yield Label(
                f"Save snippet ⇥ {self._state.trigger}",
                id="snippet-save-confirm-title",
            )
            yield Static("", id="snippet-save-confirm-header", markup=False)
            if self._state.warning:
                yield Static(
                    self._state.warning,
                    id="snippet-save-confirm-warning",
                    markup=False,
                )
            else:
                yield Static("", id="snippet-save-confirm-warning", markup=False)
            with VerticalScroll(id="snippet-save-confirm-preview-scroll"):
                yield Static("", id="snippet-save-confirm-preview", markup=False)
            yield Static("", id="snippet-save-confirm-verdict", markup=False)
            yield Static(
                "enter save · esc return · ^o preview · ^d/^u scroll",
                id="snippet-save-confirm-hints",
                markup=False,
            )

    def on_mount(self) -> None:
        self._refresh()

    def action_cycle_preview(self) -> None:
        tabs = self._tabs()
        self._preview_tab = (
            tabs[(tabs.index(self._preview_tab) + 1) % len(tabs)]
            if self._preview_tab in tabs
            else tabs[0]
        )
        self._refresh()

    def action_scroll_preview_down(self) -> None:
        scroll = self.query_one("#snippet-save-confirm-preview-scroll", VerticalScroll)
        scroll.scroll_relative(
            y=max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_scroll_preview_up(self) -> None:
        scroll = self.query_one("#snippet-save-confirm-preview-scroll", VerticalScroll)
        scroll.scroll_relative(
            y=-max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_reload_current(self) -> None:
        if self._state.changed_on_disk:
            self.dismiss("reload")

    def action_save(self) -> None:
        if not self._state.body.strip():
            self._set_verdict(
                "snippet-save-confirm-verdict-error",
                "✗ Snippet body is empty",
            )
            return
        if self._is_no_change():
            self.dismiss("close")
            return
        self.dismiss("save")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _refresh(self) -> None:
        self._refresh_header()
        self._refresh_preview()
        self._refresh_verdict()

    def _refresh_header(self) -> None:
        header = self.query_one("#snippet-save-confirm-header", Static)
        action = "Overwrite" if self._state.existing_body is not None else "Insert into"
        tabs = []
        available = self._tabs()
        for tab in ("draft", "existing", "diff"):
            label = tab.title()
            if tab == self._preview_tab:
                tabs.append(f"[{label}]")
            elif tab in available:
                tabs.append(label)
            else:
                tabs.append(f"({label})")
        header.update(f"{action} {self._state.display_path}    " + " · ".join(tabs))

    def _refresh_preview(self) -> None:
        preview = self.query_one("#snippet-save-confirm-preview", Static)
        if self._preview_tab not in self._tabs():
            self._preview_tab = "draft"
        if self._preview_tab == "draft":
            preview.update(
                Syntax(
                    self._entry_yaml(self._state.body),
                    "yaml",
                    theme="ansi_dark",
                    word_wrap=False,
                )
            )
            return
        existing_body = self._state.existing_body
        if existing_body is None:
            preview.update("No existing snippet entry.")
            return
        if self._preview_tab == "existing":
            preview.update(
                Syntax(
                    self._entry_yaml(existing_body),
                    "yaml",
                    theme="ansi_dark",
                    word_wrap=False,
                )
            )
            return
        diff = "".join(
            difflib.unified_diff(
                self._entry_yaml(existing_body).splitlines(keepends=True),
                self._entry_yaml(self._state.body).splitlines(keepends=True),
                fromfile=f"a/{Path(self._state.display_path).name}",
                tofile=f"b/{Path(self._state.display_path).name}",
            )
        )
        preview.update(
            Syntax(diff or "(no changes)\n", "diff", theme="ansi_dark", word_wrap=False)
        )

    def _refresh_verdict(self) -> None:
        if not self._state.body.strip():
            self._set_verdict(
                "snippet-save-confirm-verdict-error",
                "✗ Snippet body is empty",
            )
            return
        if self._state.changed_on_disk:
            self._set_verdict(
                "snippet-save-confirm-verdict-warning",
                (
                    f"⚠ {self._state.display_path} changed on disk · "
                    "r reload · enter overwrite anyway"
                ),
            )
            return
        if self._is_no_change():
            self._set_verdict("snippet-save-confirm-verdict-success", "✓ No changes")
            return
        verb = "Overwrite" if self._state.existing_body is not None else "Create"
        self._set_verdict(
            "snippet-save-confirm-verdict-success",
            f"✓ {verb} ⇥ {self._state.trigger} in {self._state.display_path}",
        )

    def _set_verdict(self, class_name: str, message: str) -> None:
        verdict = self.query_one("#snippet-save-confirm-verdict", Static)
        verdict.set_classes(class_name)
        verdict.update(message)

    def _is_no_change(self) -> bool:
        existing_body = self._state.existing_body
        return existing_body is not None and self._entry_yaml(
            existing_body
        ) == self._entry_yaml(self._state.body)

    def _tabs(self) -> tuple[SnippetSavePreviewTab, ...]:
        if self._state.existing_body is None:
            return ("draft",)
        return ("draft", "existing", "diff")

    def _entry_yaml(self, body: str) -> str:
        return "\n".join(generate_snippet_yaml(self._state.trigger, body)) + "\n"


__all__ = [
    "SnippetSaveConfirmModal",
    "SnippetSaveConfirmResult",
    "SnippetSaveConfirmState",
]
