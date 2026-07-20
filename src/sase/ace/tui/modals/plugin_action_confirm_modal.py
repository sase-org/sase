"""Reusable confirm-with-preview modal for plugin install / update mutations.

Every ``uv tool`` mutation surfaced in the TUI Updates tab runs through this
modal first: it shows the **exact** ``uv`` argv that would run and the resolved
scope, then asks for confirmation. The confirmation *is* the ChangeSpecI's ``--dry-run``
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

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static
from textual.worker import Worker, WorkerState

from sase.plugins.render_common import build_incoming_commits_renderable
from sase.updates.incoming_commits import RepoIncomingCommits

from .confirm_dialog import ButtonVariant, ConfirmKind

IncomingCommitsLoader = Callable[[], tuple[RepoIncomingCommits, ...]]


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
        ("ctrl+d", "scroll_commits_down", "Scroll commits down"),
        ("ctrl+u", "scroll_commits_up", "Scroll commits up"),
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
    ) -> None:
        super().__init__()
        if not variants:
            raise ValueError("PluginActionConfirmModal requires at least one variant")
        self.add_class("confirm-dialog")
        if incoming_commits_loader is not None:
            self.add_class("has-commits")
        self._title = title
        self._intro = intro
        self._variants = tuple(variants)
        self._panel_title = panel_title
        self._kind = kind
        self._icon = icon
        self._incoming_commits_loader = incoming_commits_loader
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
            yield Static(self._preview_renderable(), id="plugin-action-preview")
            if self._incoming_commits_loader is not None:
                commits = VerticalScroll(id="plugin-action-commits")
                commits.border_title = "Incoming commits"
                with commits:
                    yield Static(
                        build_incoming_commits_renderable(loading=True),
                        id="plugin-action-commits-body",
                    )
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
        if self._incoming_commits_loader is None:
            return
        self._incoming_commits_worker = self.run_worker(
            self._incoming_commits_loader,
            thread=True,
            exclusive=True,
            exit_on_error=False,
            group="confirm-incoming-commits",
        )

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
            parts.append(Text(""))

        if variant.argv:
            command = Text()
            command.append("Would run  ", style="dim")
            command.append(" ".join(variant.argv), style="cyan")
            parts.append(command)
            parts.append(Text(""))
        parts.append(Text(variant.summary, style="bold"))

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

        return Panel(
            Group(*parts),
            title=self._panel_title,
            border_style=self._accent_style(),
        )

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
            scroll.display = False
            scroll.border_subtitle = ""
            return
        parts: list[RenderableType] = []
        if len(groups) > 1:
            parts.extend(self._incoming_commit_group_summary(groups))
            parts.append(Text(""))
        parts.extend(self._incoming_commit_group_details(groups))
        scroll.display = True
        body.update(Group(*parts))
        self.call_after_refresh(self._sync_commits_scroll_hint)

    def _incoming_commit_group_summary(
        self,
        groups: tuple[RepoIncomingCommits, ...],
    ) -> list[RenderableType]:
        parts: list[RenderableType] = [Text("Repositories", style="dim")]
        for group in groups:
            incoming = group.incoming
            if incoming.source == "unavailable":
                error = incoming.error or "unknown"
                line = Text(no_wrap=True, overflow="ellipsis")
                line.append("↑", style="bold cyan")
                line.append(f" {group.label}", style="bold cyan")
                line.append(f" — incoming commits unavailable ({error})", style="dim")
                parts.append(line)
                continue

            noun = "commit" if incoming.total == 1 else "commits"
            line = Text(no_wrap=True, overflow="ellipsis")
            line.append("↑", style="bold cyan")
            line.append(f" {group.label}", style="bold cyan")
            line.append(f" — {incoming.total} incoming {noun}", style="cyan")
            if incoming.extra > 0:
                line.append(
                    f" ({incoming.shown} shown, +{incoming.extra} more)",
                    style="dim",
                )
            parts.append(line)
        return parts

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
            return
        has_overflow = int(getattr(scroll, "max_scroll_y", 0)) > 0
        if has_overflow and not self.has_class("has-scrollable-commits"):
            self.add_class("has-scrollable-commits")
            self.call_after_refresh(self._sync_commits_scroll_hint)
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
        try:
            self.query_one("#plugin-action-toggle", Button).label = self._toggle_label()
        except Exception:
            pass

    def action_confirm(self) -> None:
        self.dismiss(PluginActionConfirmResult(self._variants[self._index].key))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_scroll_commits_down(self) -> None:
        scroll = self._commits_scroll()
        if scroll is None or int(getattr(scroll, "max_scroll_y", 0)) <= 0:
            return
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=max(1, height // 2), animate=False)

    def action_scroll_commits_up(self) -> None:
        scroll = self._commits_scroll()
        if scroll is None or int(getattr(scroll, "max_scroll_y", 0)) <= 0:
            return
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(max(1, height // 2)), animate=False)

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
