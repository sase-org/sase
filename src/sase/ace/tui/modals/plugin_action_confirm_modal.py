"""Reusable confirm-with-preview modal for plugin install / update mutations.

Every ``uv tool`` mutation surfaced in the TUI Updates tab runs through this
modal first: it shows the **exact** ``uv`` argv that would run and the resolved
scope, then asks for confirmation. The confirmation *is* the PatchI's ``--dry-run``
— both safer and more discoverable than a hidden mode (epic decision *D5*).

The modal is purely presentational and reusable. A caller passes one or more
:class:`PluginActionVariant` previews (built off-thread from
:func:`sase.plugins.operations.plan_install` / ``plan_update``); with more than
one variant a toggle (``g``) cycles between them — used by the install action to
offer "from index" vs. "from git" without any further I/O. On confirm the modal
dismisses with the :class:`PluginActionConfirmResult` for the active variant; on
cancel it dismisses ``None``.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static
from textual.worker import Worker, WorkerState

from sase.plugins.render_common import build_incoming_commits_renderable
from sase.updates.incoming_commits import RepoIncomingCommits

from .confirm_dialog import ButtonVariant, ConfirmKind

IncomingCommitsLoader = Callable[[], tuple[RepoIncomingCommits, ...]]
PluginActionComponentState = Literal["update", "current", "skipped"]


@dataclass(frozen=True)
class PluginActionPreviewComponent:
    """One scannable component outcome in a composite mutation preview."""

    name: str
    detail: str
    state: PluginActionComponentState


@dataclass(frozen=True)
class PluginActionPreviewSection:
    """One titled section in a composite mutation preview."""

    title: str
    summary: str = ""
    components: tuple[PluginActionPreviewComponent, ...] = ()
    commands: tuple[str, ...] = ()
    details: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    counts: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginActionVariant:
    """One selectable preview of a mutation (e.g. install-from-index vs -git).

    *key* is the stable identifier returned on confirm so the caller can map the
    accepted variant back to its planned ``*Ready`` outcome; *label* names the
    variant in the toggle; *argv* is the exact ``uv`` command shown verbatim;
    *summary* describes the resolved plugin set / source.
    """

    key: str
    label: str
    argv: tuple[str, ...]
    summary: str
    details: tuple[str, ...] = ()
    items: tuple[str, ...] = ()
    items_label: str = "Plugins"
    skipped: tuple[str, ...] = ()
    sections: tuple[PluginActionPreviewSection, ...] = ()


@dataclass(frozen=True)
class PluginActionConfirmResult:
    """The confirmed choice: which variant the user accepted."""

    variant_key: str


class PluginActionConfirmModal(ModalScreen[PluginActionConfirmResult | None]):
    """Confirm a plugin mutation after previewing its exact ``uv`` command."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("n", "cancel", "Cancel"),
        ("y", "confirm", "Confirm"),
        ("g", "toggle_source", "Toggle source"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(
        self,
        *,
        title: str,
        intro: str,
        variants: Sequence[PluginActionVariant],
        panel_title: str = "Confirm",
        kind: ConfirmKind = ConfirmKind.NEUTRAL,
        icon: str | None = None,
        incoming_commits_loader: IncomingCommitsLoader | None = None,
        incoming_commits_empty_message: str | None = None,
    ) -> None:
        super().__init__()
        if not variants:
            raise ValueError("PluginActionConfirmModal requires at least one variant")
        self.add_class("confirm-dialog")
        self._show_incoming_commits = (
            incoming_commits_loader is not None
            or incoming_commits_empty_message is not None
        )
        if self._show_incoming_commits:
            self.add_class("has-commits")
        if any(variant.sections for variant in variants):
            self.add_class("has-sections")
        self._title = title
        self._intro = intro
        self._variants = tuple(variants)
        self._panel_title = panel_title
        self._kind = kind
        self._icon = icon
        self._incoming_commits_loader = incoming_commits_loader
        self._incoming_commits_empty_message = incoming_commits_empty_message
        self._incoming_commits_worker: Worker[Any] | None = None
        self._index = 0

    def compose(self) -> ComposeResult:
        dialog = Container(
            id="plugin-action-container",
            classes=f"confirm-dialog-panel confirm-dialog--{self._kind.value}",
        )
        dialog.border_title = self._build_border_title()
        dialog.border_subtitle = self._build_border_subtitle()
        with dialog:
            if self._show_incoming_commits:
                commits = VerticalScroll(id="plugin-action-commits")
                commits.border_title = "Incoming commits"
                with commits:
                    yield Static(
                        build_incoming_commits_renderable(loading=True)
                        if self._incoming_commits_loader is not None
                        else Text(
                            self._incoming_commits_empty_message or "",
                            style="dim",
                        ),
                        id="plugin-action-commits-body",
                    )
            preview_scroll = VerticalScroll(id="plugin-action-preview-scroll")
            preview_scroll.border_title = self._panel_title
            with preview_scroll:
                yield Static(self._preview_renderable(), id="plugin-action-preview")
            with Horizontal(id="plugin-action-buttons"):
                yield Button(
                    "Confirm (y)",
                    id="plugin-action-confirm",
                    variant=self._confirm_button_variant(),
                )
                if len(self._variants) > 1:
                    yield Button(
                        self._toggle_label(),
                        id="plugin-action-toggle",
                        variant="primary",
                    )
                yield Button(
                    "Cancel (n)",
                    id="plugin-action-cancel",
                    variant=self._cancel_button_variant(),
                )

    def on_mount(self) -> None:
        self.call_after_refresh(self._sync_preview_scroll_hint)
        if self._show_incoming_commits:
            self.call_after_refresh(self._sync_commits_scroll_hint)
        if self._incoming_commits_loader is None:
            return
        self._incoming_commits_worker = self.run_worker(
            self._incoming_commits_loader,
            thread=True,
            exclusive=True,
            exit_on_error=False,
            group="confirm-incoming-commits",
        )

    def on_unmount(self) -> None:
        worker = self._incoming_commits_worker
        self._incoming_commits_worker = None
        if worker is not None:
            worker.cancel()

    def on_resize(self, _event: events.Resize) -> None:
        self.call_after_refresh(self._sync_preview_scroll_hint)
        if self._show_incoming_commits:
            self.call_after_refresh(self._sync_commits_scroll_hint)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._incoming_commits_worker:
            return
        if event.state == WorkerState.SUCCESS:
            self._incoming_commits_worker = None
            result = event.worker.result
            if isinstance(result, tuple):
                self._apply_incoming_commit_groups(result)
            else:
                self._apply_incoming_commits_error("unexpected loader result")
        elif event.state == WorkerState.ERROR:
            self._incoming_commits_worker = None
            error = event.worker.error
            detail = str(error).strip() if error is not None else "unknown"
            self._apply_incoming_commits_error(detail or type(error).__name__)
        elif event.state == WorkerState.CANCELLED:
            self._incoming_commits_worker = None

    # -- rendering --

    def _preview_renderable(self) -> RenderableType:
        variant = self._variants[self._index]
        parts: list[RenderableType] = []
        if self._intro:
            parts.append(Text(self._intro, style="dim"))

        if variant.argv:
            if parts:
                parts.append(Text(""))
            parts.append(Text("Would run", style="dim"))
            parts.append(self._command_renderable(shlex.join(variant.argv)))
        parts.append(Text(variant.summary, style="bold"))

        for section in variant.sections:
            parts.append(Text(""))
            parts.append(self._section_rule(section))
            if section.summary:
                parts.append(Text(section.summary, style="dim"))
            if section.components:
                parts.append(self._components_renderable(section.components))
            for detail in section.details:
                line = Text()
                line.append("- ", style="dim")
                line.append(detail, style="dim")
                parts.append(line)
            if section.commands:
                parts.append(Text("commands", style="dim"))
                for item in section.commands:
                    parts.append(self._command_renderable(item))
            if section.skipped and not section.components:
                parts.append(Text("Manual / skipped", style="yellow"))
                for item in section.skipped:
                    line = Text()
                    line.append("- ", style="dim")
                    line.append(item, style="yellow")
                    parts.append(line)

        if variant.items:
            parts.append(Text(""))
            parts.append(Text(variant.items_label, style="dim"))
            for item in variant.items:
                line = Text()
                line.append("- ", style="dim")
                line.append(item)
                parts.append(line)

        if variant.skipped:
            parts.append(Text(""))
            parts.append(Text("Skipped", style="yellow"))
            for item in variant.skipped:
                line = Text()
                line.append("- ", style="dim")
                line.append(item, style="yellow")
                parts.append(line)

        if variant.details:
            parts.append(Text(""))
            for detail in variant.details:
                line = Text()
                line.append("- ", style="dim")
                line.append(detail, style="dim")
                parts.append(line)

        if len(self._variants) > 1:
            parts.append(Text(""))
            parts.append(self._source_line())

        return Group(*parts)

    def _section_rule(self, section: PluginActionPreviewSection) -> Rule:
        title = Text()
        title.append(section.title, style="bold cyan")
        for count in section.counts:
            title.append(f" · {count}", style="dim")
        return Rule(title, style="cyan")

    @staticmethod
    def _components_renderable(
        components: tuple[PluginActionPreviewComponent, ...],
    ) -> Table:
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(width=1, no_wrap=True)
        table.add_column(no_wrap=True)
        table.add_column(ratio=1, overflow="fold")
        for component in components:
            glyph, style = {
                "update": ("↑", "bold cyan"),
                "current": ("✓", "dim green"),
                "skipped": ("•", "yellow"),
            }[component.state]
            table.add_row(
                Text(glyph, style=style),
                Text(component.name, style=style),
                Text(component.detail, style="dim"),
            )
        return table

    def _command_renderable(self, command: str) -> RenderableType:
        if command.startswith("fallback: "):
            line = Text()
            line.append("fallback:  ", style="dim")
            line.append("$ ", style="dim")
            line.append(
                self._display_command(command.removeprefix("fallback: ")),
                style="dim cyan",
            )
            return Padding(line, (0, 0, 0, 4), expand=False)

        label, exact_command = self._split_command_label(command)
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(width=1, no_wrap=True)
        table.add_column(ratio=1, overflow="fold")
        if label:
            table.add_row(Text("", style="dim"), Text(label, style="dim"))
        table.add_row(
            Text("$", style="dim"),
            Text(self._display_command(exact_command), style="cyan"),
        )
        return Padding(table, (0, 0, 0, 1), expand=False)

    @staticmethod
    def _split_command_label(command: str) -> tuple[str, str]:
        match = re.match(r"^([^/:]{1,48}): (.+)$", command)
        if match is None:
            return "", command
        return match.group(1), match.group(2)

    @staticmethod
    def _display_command(command: str) -> str:
        """Shorten the home prefix for display without changing stored argv."""
        user_home = os.environ.get("HOME", "").rstrip("/")
        if not user_home:
            return command
        return command.replace(f"{user_home}/", "~/")

    def _source_line(self) -> Text:
        line = Text()
        line.append("Source  ", style="dim")
        for index, variant in enumerate(self._variants):
            if index > 0:
                line.append("  /  ", style="dim")
            active = index == self._index
            line.append(
                variant.label,
                style=f"bold {self._accent_style()}" if active else "dim",
            )
        line.append("   (g to switch)", style="dim")
        return line

    def _toggle_label(self) -> str:
        nxt = self._variants[(self._index + 1) % len(self._variants)]
        return f"Source: {nxt.label} (g)"

    def _build_border_title(self) -> Text:
        title = Text()
        title.append(self._icon or self._default_icon(), style=self._title_icon_style())
        title.append("  ")
        title.append(self._title, style="bold")
        return title

    def _build_border_subtitle(self) -> str:
        if len(self._variants) > 1:
            return "y confirm · n/esc cancel · g source"
        return "y confirm · n/esc cancel"

    def _default_icon(self) -> str:
        return "!" if self._kind is ConfirmKind.DANGER else "?"

    def _title_icon_style(self) -> str:
        return "bold red" if self._kind is ConfirmKind.DANGER else "bold cyan"

    def _accent_style(self) -> str:
        return "red" if self._kind is ConfirmKind.DANGER else "cyan"

    def _confirm_button_variant(self) -> ButtonVariant:
        return "error" if self._kind is ConfirmKind.DANGER else "primary"

    def _cancel_button_variant(self) -> ButtonVariant:
        return "primary" if self._kind is ConfirmKind.DANGER else "default"

    def _apply_incoming_commit_groups(
        self,
        groups: tuple[RepoIncomingCommits, ...],
    ) -> None:
        widgets = self._commits_widgets()
        if widgets is None:
            return
        scroll, body = widgets
        if not groups:
            if self._incoming_commits_empty_message is None:
                scroll.display = False
            else:
                scroll.display = True
                body.update(Text(self._incoming_commits_empty_message, style="dim"))
            scroll.border_subtitle = ""
            self.remove_class("has-scrollable-commits")
            return
        parts: list[RenderableType] = []
        if len(groups) > 1:
            parts.extend(self._incoming_commit_aggregate(groups))
        parts.extend(self._incoming_commit_group_details(groups))
        scroll.display = True
        body.update(Group(*parts))
        self.call_after_refresh(self._sync_commits_scroll_hint)

    def _incoming_commit_aggregate(
        self,
        groups: tuple[RepoIncomingCommits, ...],
    ) -> list[RenderableType]:
        repository_count = len(groups)
        commit_count = sum(
            group.incoming.total
            for group in groups
            if group.incoming.source != "unavailable"
        )
        unavailable_count = sum(
            group.incoming.source == "unavailable" for group in groups
        )
        repository_noun = "repository" if repository_count == 1 else "repositories"
        commit_noun = "commit" if commit_count == 1 else "commits"
        line = Text()
        line.append(
            f"{repository_count} {repository_noun}",
            style="bold cyan",
        )
        line.append(f" · {commit_count} incoming {commit_noun}", style="cyan")
        if unavailable_count:
            line.append(f" · {unavailable_count} unavailable", style="dim")
        return [line]

    def _incoming_commit_group_details(
        self,
        groups: tuple[RepoIncomingCommits, ...],
    ) -> list[RenderableType]:
        parts: list[RenderableType] = []
        for index, group in enumerate(groups):
            if index > 0:
                parts.append(Text(""))
            parts.append(
                build_incoming_commits_renderable(group.incoming, label=group.label)
            )
        return parts

    def _apply_incoming_commits_error(self, detail: str) -> None:
        widgets = self._commits_widgets()
        if widgets is None:
            return
        scroll, body = widgets
        scroll.display = True
        body.update(Text(f"incoming commits unavailable ({detail})", style="dim"))
        self.call_after_refresh(self._sync_commits_scroll_hint)

    def _sync_commits_scroll_hint(self) -> None:
        widgets = self._commits_widgets()
        if widgets is None:
            return
        scroll, _body = widgets
        if not scroll.display:
            self.remove_class("has-scrollable-commits")
            return
        has_overflow = int(getattr(scroll, "max_scroll_y", 0)) > 0
        class_is_set = self.has_class("has-scrollable-commits")
        if has_overflow != class_is_set:
            if has_overflow:
                self.add_class("has-scrollable-commits")
            else:
                self.remove_class("has-scrollable-commits")
            self.call_after_refresh(self._sync_commits_scroll_hint)
            return
        scroll.border_subtitle = "ctrl+d/u scroll" if has_overflow else ""

    def _sync_preview_scroll_hint(self) -> None:
        scroll = self._preview_scroll()
        if scroll is None:
            return
        has_overflow = int(getattr(scroll, "max_scroll_y", 0)) > 0
        class_is_set = self.has_class("has-scrollable-preview")
        if has_overflow != class_is_set:
            if has_overflow:
                self.add_class("has-scrollable-preview")
            else:
                self.remove_class("has-scrollable-preview")
            self.call_after_refresh(self._sync_preview_scroll_hint)
            return
        scroll.border_subtitle = "ctrl+d/u scroll" if has_overflow else ""

    def _commits_widgets(self) -> tuple[VerticalScroll, Static] | None:
        if not getattr(self, "is_attached", True):
            return None
        try:
            return (
                self.query_one("#plugin-action-commits", VerticalScroll),
                self.query_one("#plugin-action-commits-body", Static),
            )
        except Exception:
            return None

    def _preview_scroll(self) -> VerticalScroll | None:
        if not getattr(self, "is_attached", True):
            return None
        try:
            return self.query_one("#plugin-action-preview-scroll", VerticalScroll)
        except Exception:
            return None

    # -- actions --

    def action_toggle_source(self) -> None:
        """Cycle to the next preview variant (e.g. index ↔ git)."""
        if len(self._variants) <= 1:
            return
        self._index = (self._index + 1) % len(self._variants)
        try:
            self.query_one("#plugin-action-preview", Static).update(
                self._preview_renderable()
            )
        except Exception:
            pass
        scroll = self._preview_scroll()
        if scroll is not None:
            scroll.scroll_to(y=0, animate=False)
        self.call_after_refresh(self._sync_preview_scroll_hint)
        try:
            self.query_one("#plugin-action-toggle", Button).label = self._toggle_label()
        except Exception:
            pass

    def action_confirm(self) -> None:
        self.dismiss(PluginActionConfirmResult(self._variants[self._index].key))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        for scroll in (self._commits_scroll(), self._preview_scroll()):
            if scroll is None or not self._can_scroll_down(scroll):
                continue
            height = scroll.scrollable_content_region.height
            scroll.scroll_relative(y=max(1, height // 2), animate=False)
            return

    def action_scroll_up(self) -> None:
        for scroll in (self._preview_scroll(), self._commits_scroll()):
            if scroll is None or not self._can_scroll_up(scroll):
                continue
            height = scroll.scrollable_content_region.height
            scroll.scroll_relative(y=-(max(1, height // 2)), animate=False)
            return

    @staticmethod
    def _can_scroll_down(scroll: VerticalScroll) -> bool:
        return float(scroll.scroll_y) < int(getattr(scroll, "max_scroll_y", 0))

    @staticmethod
    def _can_scroll_up(scroll: VerticalScroll) -> bool:
        return float(scroll.scroll_y) > 0

    def _commits_scroll(self) -> VerticalScroll | None:
        widgets = self._commits_widgets()
        if widgets is None:
            return None
        scroll, _body = widgets
        if not scroll.display:
            return None
        return scroll

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "plugin-action-confirm":
            self.action_confirm()
        elif event.button.id == "plugin-action-toggle":
            self.action_toggle_source()
        else:
            self.action_cancel()
