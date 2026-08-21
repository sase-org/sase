"""Confirmation panel for saving a pane-scoped mini-xprompt draft."""

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
import yaml  # type: ignore[import-untyped]

from sase.ace.tui.widgets.prompt_stack import split_frontmatter
from sase.xprompt.config_yaml import generate_xprompt_yaml
from sase.xprompt.loader_parsing import parse_yaml_front_matter
from sase.xprompt.models import XPrompt
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import SaveTargetFormat, build_markdown_xprompt
from sase.xprompt.segment_separators import xprompt_has_segment_separators

MiniXPromptSaveConfirmResult = Literal[
    "save",
    "overwrite",
    "close",
    "reload",
    "retarget",
]
MiniXPromptSavePreviewTab = Literal["draft", "existing", "diff"]


@dataclass(frozen=True, slots=True)
class MiniXPromptSaveConfirmState:
    """All disk-backed facts needed to confirm one mini-xprompt save."""

    name: str
    display_path: str
    body: str
    frontmatter: str
    target_format: SaveTargetFormat
    entry_name: str | None
    exists: bool
    existing_markdown: str | None
    changed_on_disk: bool = False
    warning: str | None = None


class MiniXPromptSaveConfirmModal(
    ModalScreen[MiniXPromptSaveConfirmResult | None],
):
    """Show the final xprompt document or config entry before writing."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "save", "Save", show=False),
        Binding("o", "overwrite_changed", "Overwrite", show=False),
        Binding("r", "reload_current", "Reload", show=False),
        Binding("a", "retarget", "Retarget", show=False),
        Binding("ctrl+o", "cycle_preview", "Cycle preview", show=False),
        Binding("ctrl+d", "scroll_preview_down", "Scroll down", show=False),
        Binding("ctrl+u", "scroll_preview_up", "Scroll up", show=False),
    ]

    def __init__(self, state: MiniXPromptSaveConfirmState) -> None:
        super().__init__()
        self._state = state
        self._preview_tab: MiniXPromptSavePreviewTab = (
            "diff" if state.existing_markdown is not None else "draft"
        )

    def compose(self) -> ComposeResult:
        with Container(id="mini-xprompt-save-confirm-container"):
            yield Label(
                f"Save mini-xprompt #{self._state.name}",
                id="mini-xprompt-save-confirm-title",
            )
            yield Static("", id="mini-xprompt-save-confirm-header", markup=False)
            if self._state.warning:
                yield Static(
                    self._state.warning,
                    id="mini-xprompt-save-confirm-warning",
                    markup=False,
                )
            else:
                yield Static("", id="mini-xprompt-save-confirm-warning", markup=False)
            with VerticalScroll(id="mini-xprompt-save-confirm-preview-scroll"):
                yield Static("", id="mini-xprompt-save-confirm-preview", markup=False)
            yield Static("", id="mini-xprompt-save-confirm-verdict", markup=False)
            yield Static(
                "enter save · esc return · ^o preview · r reload · a retarget",
                id="mini-xprompt-save-confirm-hints",
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
        scroll = self.query_one(
            "#mini-xprompt-save-confirm-preview-scroll", VerticalScroll
        )
        scroll.scroll_relative(
            y=max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_scroll_preview_up(self) -> None:
        scroll = self.query_one(
            "#mini-xprompt-save-confirm-preview-scroll", VerticalScroll
        )
        scroll.scroll_relative(
            y=-max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_reload_current(self) -> None:
        if self._state.changed_on_disk:
            self.dismiss("reload")

    def action_retarget(self) -> None:
        self.dismiss("retarget")

    def action_overwrite_changed(self) -> None:
        if self._state.changed_on_disk:
            error = _save_blocker(self._state)
            if error is None:
                self.dismiss("overwrite")
            else:
                self._set_verdict("mini-xprompt-save-confirm-verdict-error", error)

    def action_save(self) -> None:
        error = _save_blocker(self._state)
        if error is not None:
            self._set_verdict("mini-xprompt-save-confirm-verdict-error", error)
            return
        if self._is_no_change():
            self.dismiss("close")
            return
        if self._state.changed_on_disk:
            self._set_verdict(
                "mini-xprompt-save-confirm-verdict-warning",
                (
                    f"{self._state.display_path} changed on disk · "
                    "o overwrite · r reload · a retarget"
                ),
            )
            return
        self.dismiss("save")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _refresh(self) -> None:
        self._refresh_header()
        self._refresh_preview()
        self._refresh_verdict()

    def _refresh_header(self) -> None:
        header = self.query_one("#mini-xprompt-save-confirm-header", Static)
        action = (
            "Overwrite" if self._state.existing_markdown is not None else "Create in"
        )
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
        preview = self.query_one("#mini-xprompt-save-confirm-preview", Static)
        if self._preview_tab not in self._tabs():
            self._preview_tab = "draft"
        try:
            if self._preview_tab == "draft":
                preview.update(self._syntax(_draft_preview(self._state)))
                return
            existing = self._state.existing_markdown
            if existing is None:
                preview.update("No existing mini-xprompt definition.")
                return
            if self._preview_tab == "existing":
                preview.update(self._syntax(_existing_preview(self._state, existing)))
                return
            draft = _draft_preview(self._state)
            old = _existing_preview(self._state, existing)
        except ValueError as exc:
            preview.update(f"Cannot render preview: {exc}")
            return
        diff = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                draft.splitlines(keepends=True),
                fromfile=f"a/{Path(self._state.display_path).name}",
                tofile=f"b/{Path(self._state.display_path).name}",
            )
        )
        preview.update(
            Syntax(diff or "(no changes)\n", "diff", theme="ansi_dark", word_wrap=False)
        )

    def _refresh_verdict(self) -> None:
        error = _save_blocker(self._state)
        if error is not None:
            self._set_verdict("mini-xprompt-save-confirm-verdict-error", error)
            return
        if self._state.changed_on_disk:
            self._set_verdict(
                "mini-xprompt-save-confirm-verdict-warning",
                (
                    f"{self._state.display_path} changed on disk · "
                    "o overwrite · r reload · a retarget"
                ),
            )
            return
        if self._is_no_change():
            self._set_verdict("mini-xprompt-save-confirm-verdict-success", "No changes")
            return
        verb = "Overwrite" if self._state.existing_markdown is not None else "Create"
        self._set_verdict(
            "mini-xprompt-save-confirm-verdict-success",
            f"{verb} #{self._state.name} in {self._state.display_path}",
        )

    def _set_verdict(self, class_name: str, message: str) -> None:
        verdict = self.query_one("#mini-xprompt-save-confirm-verdict", Static)
        verdict.set_classes(class_name)
        verdict.update(message)

    def _is_no_change(self) -> bool:
        existing = self._state.existing_markdown
        if existing is None:
            return False
        try:
            return _existing_preview(self._state, existing) == _draft_preview(
                self._state
            )
        except ValueError:
            return False

    def _tabs(self) -> tuple[MiniXPromptSavePreviewTab, ...]:
        if self._state.existing_markdown is None:
            return ("draft",)
        return ("draft", "existing", "diff")

    def _syntax(self, text: str) -> Syntax:
        syntax = (
            "yaml"
            if self._state.target_format is SaveTargetFormat.CONFIG
            else "markdown"
        )
        return Syntax(text, syntax, theme="ansi_dark", word_wrap=False)


def _save_blocker(state: MiniXPromptSaveConfirmState) -> str | None:
    if not state.body.strip():
        return "Mini-xprompt body is empty"
    try:
        frontmatter = _frontmatter_for_save(state.frontmatter)
    except ValueError as exc:
        return str(exc)
    if state.target_format is SaveTargetFormat.CONFIG and frontmatter.skill:
        return "Config-backed xprompts cannot declare skill:"
    if xprompt_has_segment_separators(XPrompt(name=state.name, content=state.body)):
        return "Mini-xprompt body contains a top-level --- swarm separator"
    return None


def _frontmatter_for_save(raw: str) -> PromptFrontmatter:
    """Parse frontmatter strictly enough for a final save decision."""
    text = raw.strip()
    if not text:
        return PromptFrontmatter()
    if text.startswith("---"):
        mapping, _ = parse_yaml_front_matter(text)
        if mapping is None:
            raise ValueError("Frontmatter block is invalid or unterminated")
    else:
        try:
            mapping = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Frontmatter YAML is invalid: {exc}") from exc
        if mapping is not None and not isinstance(mapping, dict):
            raise ValueError("Frontmatter must be a YAML mapping")
    try:
        return PromptFrontmatter.parse(raw)
    except Exception as exc:
        raise ValueError(f"Frontmatter is invalid: {exc}") from exc


def _draft_preview(state: MiniXPromptSaveConfirmState) -> str:
    if state.target_format is SaveTargetFormat.CONFIG:
        frontmatter = _frontmatter_for_save(state.frontmatter)
        return _config_entry_preview(
            state.entry_name or state.name,
            frontmatter,
            state.body,
        )
    if state.existing_markdown is not None:
        existing_frontmatter, existing_body = split_frontmatter(state.existing_markdown)
        if (
            existing_frontmatter == state.frontmatter
            and existing_body.strip() == state.body.strip()
        ):
            return state.existing_markdown
    return _markdown_preview(state.frontmatter, state.body)


def _existing_preview(state: MiniXPromptSaveConfirmState, markdown: str) -> str:
    if state.target_format is SaveTargetFormat.CONFIG:
        frontmatter, body = split_frontmatter(markdown)
        return _config_entry_preview(
            state.entry_name or state.name,
            _frontmatter_for_save(frontmatter),
            body,
        )
    return markdown


def _markdown_preview(frontmatter: str, body: str) -> str:
    if frontmatter.strip():
        return _raw_markdown_xprompt(frontmatter, body)
    return build_markdown_xprompt(PromptFrontmatter(), body)


def _raw_markdown_xprompt(frontmatter: str, body: str) -> str:
    clean_frontmatter = frontmatter.strip()
    clean_body = body.rstrip()
    if clean_frontmatter and clean_body:
        return f"{clean_frontmatter}\n\n{clean_body}\n"
    if clean_frontmatter:
        return f"{clean_frontmatter}\n"
    return f"{clean_body}\n"


def _config_entry_preview(
    name: str,
    frontmatter: PromptFrontmatter,
    body: str,
) -> str:
    lines = [
        "xprompts:",
        *generate_xprompt_yaml(name, [], body, frontmatter=frontmatter),
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "MiniXPromptSaveConfirmModal",
    "MiniXPromptSaveConfirmResult",
    "MiniXPromptSaveConfirmState",
    "MiniXPromptSavePreviewTab",
]
