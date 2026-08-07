"""Gate lifecycle and artifact diagnostics for ACE notification surfaces."""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from typing import TYPE_CHECKING, Any

from rich.markup import escape
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.util.pump_tasks import (
    cancel_pump_free_tasks,
    spawn_pump_free_task,
)
from sase.notification_gates.debug import (
    GateDebugArtifact,
    GateDebugContext,
    GateDebugSnapshot,
    build_gate_debug_snapshot,
)

from .base import CopyModeForwardingMixin

if TYPE_CHECKING:
    from pathlib import Path


_TAB_NAMES = ("Overview", "Request", "Response", "Errors", "Row")
_KIND_COLORS = {
    "plan": "#ff87d7",
    "epic": "#d787ff",
    "epic_plan": "#d787ff",
    "question": "#87d7ff",
    "launch": "#5fffff",
    "task_triage": "#d787ff",
    "custom": "#ffaf5f",
    "hitl": "#ffd75f",
    "notification": "#a8a8a8",
}
_STATUS_COLORS = {
    "PENDING": "#ffd75f",
    "ANSWERED": "#5fff87",
    "CANCELLED": "#ff5f5f",
    "TIMED OUT": "#ff5f5f",
    "OVERDUE": "#ff5f5f",
    "UNKNOWN": "#808080",
}


class GateDebugModal(CopyModeForwardingMixin, ModalScreen[None]):
    """Scrollable tabbed debug view loaded without blocking Textual's pump."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("d", "close", "Close"),
        ("left_square_bracket", "previous_tab", "Previous tab"),
        ("right_square_bracket", "next_tab", "Next tab"),
        ("j", "scroll_down_line", "Down"),
        ("k", "scroll_up_line", "Up"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
        ("y", "copy_tab", "Copy tab"),
        ("Y", "copy_bundle_path", "Copy bundle path"),
        ("e", "open_backing_file", "Edit"),
    ]

    def __init__(self, context: GateDebugContext) -> None:
        super().__init__()
        self._debug_context = context
        self._snapshot: GateDebugSnapshot | None = None
        self._tab_index = 0
        self._gate_debug_tasks: set[asyncio.Task[Any]] = set()
        kind = _context_kind(context)
        self.add_class(f"kind-{kind if kind in _KIND_COLORS else 'notification'}")

    def compose(self) -> ComposeResult:
        with Container(id="gate-debug-container"):
            yield Static(self._loading_header(), id="gate-debug-header")
            yield Static(self._tab_strip(), id="gate-debug-tabs")
            with VerticalScroll(id="gate-debug-scroll"):
                yield Static(
                    Text("Loading gate lifecycle and artifacts…", style="italic dim"),
                    id="gate-debug-content",
                )
            yield Static(
                Text(
                    "[]: tabs  j/k · Ctrl+D/U · g/G: scroll  y: copy tab  "
                    "Y: copy bundle  e: edit  d/q/Esc: close"
                ),
                id="gate-debug-footer",
            )

    def on_mount(self) -> None:
        task = spawn_pump_free_task(
            self,
            self._load(),
            name=f"gate-debug-load:{self._debug_context.notification.id}",
            registry_attr="_gate_debug_tasks",
        )
        if task is None:
            self.query_one("#gate-debug-content", Static).update(
                "Gate debug loading is unavailable."
            )

    def on_unmount(self) -> None:
        cancel_pump_free_tasks(self)

    async def _load(self) -> None:
        try:
            snapshot = await asyncio.to_thread(
                build_gate_debug_snapshot,
                self._debug_context.notification,
                self._debug_context.action_data,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # defensive: the debug view must diagnose itself
            if self.is_mounted:
                self.query_one("#gate-debug-content", Static).update(
                    Text(f"Gate debug snapshot failed: {exc}", style="bold red")
                )
            return
        if not self.is_mounted:
            return
        self._snapshot = snapshot
        self._apply_kind_class(snapshot.kind)
        self.query_one("#gate-debug-header", Static).update(self._header(snapshot))
        self.query_one("#gate-debug-tabs", Static).update(self._tab_strip())
        self._render_tab(reset_scroll=True)

    def _apply_kind_class(self, kind: str) -> None:
        for candidate in _KIND_COLORS:
            self.remove_class(f"kind-{candidate}")
        self.add_class(f"kind-{kind if kind in _KIND_COLORS else 'notification'}")

    def _loading_header(self) -> Text:
        notification = self._debug_context.notification
        kind = _context_kind(self._debug_context)
        request_id = str(
            self._debug_context.action_data.get("request_id") or notification.id
        )
        text = Text()
        text.append(f"{notification.icon or '🔔'}  ")
        text.append(kind.upper(), style=f"bold {_KIND_COLORS.get(kind, '#a8a8a8')}")
        text.append(f"  {request_id}", style="dim")
        text.append("    LOADING", style="bold #ffd75f")
        return text

    @staticmethod
    def _header(snapshot: GateDebugSnapshot) -> Text:
        color = _KIND_COLORS.get(snapshot.kind, _KIND_COLORS["notification"])
        status_color = _STATUS_COLORS[snapshot.status]
        text = Text()
        text.append(f"{snapshot.icon}  ")
        text.append(snapshot.kind.upper(), style=f"bold {color}")
        text.append(f"  {snapshot.request_id}", style="bold")
        text.append(f"    {snapshot.status}", style=f"bold reverse {status_color}")
        text.append(f"    {snapshot.age}", style="dim")
        return text

    def _tab_strip(self) -> Text:
        labels = list(_TAB_NAMES)
        if self._snapshot is not None:
            labels[3] = f"Errors ({self._snapshot.error_count})"
        text = Text()
        for index, label in enumerate(labels):
            if index:
                text.append("   ", style="dim")
            style = "bold reverse #87d7ff" if index == self._tab_index else "dim"
            text.append(f" {label} ", style=style)
        return text

    def _artifact_for_tab(self) -> GateDebugArtifact | None:
        if self._snapshot is None:
            return None
        return (
            self._snapshot.overview,
            self._snapshot.request,
            self._snapshot.response,
            self._snapshot.errors_artifact,
            self._snapshot.row,
        )[self._tab_index]

    def _render_tab(self, *, reset_scroll: bool = False) -> None:
        artifact = self._artifact_for_tab()
        if artifact is None:
            return
        content: Any
        if self._tab_index in (1, 2, 4) and artifact.status == "ok":
            content = Syntax(
                artifact.body,
                "json",
                theme="monokai",
                word_wrap=True,
            )
        else:
            content = Text(artifact.body)
        self.query_one("#gate-debug-content", Static).update(content)
        self.query_one("#gate-debug-tabs", Static).update(self._tab_strip())
        if reset_scroll:
            self.query_one("#gate-debug-scroll", VerticalScroll).scroll_home(
                animate=False
            )

    def action_previous_tab(self) -> None:
        if self._snapshot is None:
            return
        self._tab_index = (self._tab_index - 1) % len(_TAB_NAMES)
        self._render_tab(reset_scroll=True)

    def action_next_tab(self) -> None:
        if self._snapshot is None:
            return
        self._tab_index = (self._tab_index + 1) % len(_TAB_NAMES)
        self._render_tab(reset_scroll=True)

    def action_scroll_down_line(self) -> None:
        self.query_one("#gate-debug-scroll", VerticalScroll).scroll_relative(
            y=1, animate=False
        )

    def action_scroll_up_line(self) -> None:
        self.query_one("#gate-debug-scroll", VerticalScroll).scroll_relative(
            y=-1, animate=False
        )

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#gate-debug-scroll", VerticalScroll)
        scroll.scroll_relative(
            y=max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#gate-debug-scroll", VerticalScroll)
        scroll.scroll_relative(
            y=-max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_scroll_to_top(self) -> None:
        self.query_one("#gate-debug-scroll", VerticalScroll).scroll_home(animate=False)

    def action_scroll_to_bottom(self) -> None:
        self.query_one("#gate-debug-scroll", VerticalScroll).scroll_end(animate=False)

    def action_copy_tab(self) -> None:
        artifact = self._artifact_for_tab()
        if artifact is None:
            self.notify("Gate debug data is still loading", severity="warning")
            return
        schedule_copy_delivery(
            self,
            artifact.raw_text,
            copied_label=f"{_TAB_NAMES[self._tab_index]} debug data",
            task_name="sase-copy-gate-debug-tab",
        )

    def action_copy_bundle_path(self) -> None:
        path = self._bundle_path()
        if path is None:
            self.notify("No gate bundle path to copy", severity="warning")
            return
        schedule_copy_delivery(
            self,
            str(path),
            copied_label=f"gate bundle path ({path})",
            task_name="sase-copy-gate-bundle-path",
        )

    def action_open_backing_file(self) -> None:
        path = self._backing_path()
        if path is None:
            self.notify("This debug tab has no backing file", severity="warning")
            return
        editor = os.environ.get("EDITOR") or "nvim"
        try:
            with self.app.suspend():
                subprocess.call([*shlex.split(editor), str(path)])
        except Exception as exc:
            self.notify(f"Could not open {escape(str(path))}: {exc}", severity="error")

    def _bundle_path(self) -> Path | None:
        if self._snapshot is not None:
            return self._snapshot.bundle_path
        raw = self._debug_context.action_data.get("bundle_path")
        if not raw:
            return None
        from pathlib import Path

        return Path(raw).expanduser()

    def _backing_path(self) -> Path | None:
        if self._snapshot is None:
            return None
        if self._tab_index == 0:
            return self._snapshot.request.path
        if self._tab_index == 3 and self._snapshot.errors:
            return self._snapshot.errors[0].path
        artifact = self._artifact_for_tab()
        return artifact.path if artifact is not None else None

    def action_close(self) -> None:
        self.dismiss(None)


def show_gate_debug(modal: Any, context: GateDebugContext | None) -> None:
    """Open Gate Debug above a gate modal, or explain missing context quietly."""
    if context is None:
        modal.notify(
            "Gate debug context is unavailable for this view",
            severity="warning",
        )
        return
    modal.app.push_screen(GateDebugModal(context))


def _context_kind(context: GateDebugContext) -> str:
    projected = context.action_data.get("request_kind")
    if projected:
        return str(projected)
    action = context.notification.action
    if action is None:
        return "notification"
    return {
        "PlanApproval": "plan",
        "EpicApproval": "epic_plan",
        "UserQuestion": "question",
        "LaunchApproval": "launch",
        "TaskTriage": "task_triage",
        "BeadSnooze": "bead_snooze",
        "CustomGate": "custom",
        "HITL": "hitl",
    }.get(action, "notification")


__all__ = ["GateDebugModal", "show_gate_debug"]
