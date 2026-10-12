"""Progress stage for the New Project wizard."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from time import monotonic
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from sase.ace.tui._proc_observer_models import proc_status_is_active
from sase.ace.tui._proc_observer_store import DETAIL_LOG_LINES
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks, spawn_pump_free_task
from sase.procs import read_proc_log_tail

from .new_project_progress_model import (
    ProgressResult,
    ProgressStep,
    ProgressView,
    reduce_lines,
)
from .new_project_rendering import clean_source_text

_TASKS = "_new_project_progress_tasks"
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_POLL_SECONDS = 0.25
_RAW_TAIL = 12


def format_elapsed(seconds: float) -> str:
    """Format a running-step duration for the checklist."""
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, remain = divmod(total, 60)
    return f"{minutes}m {remain:02d}s"


def render_checklist(
    steps: Sequence[ProgressStep],
    *,
    running_glyph: str = "⠋",
    elapsed_by_id: Mapping[str, str] | None = None,
) -> Text:
    """Render checklist rows with the apply-ready glyphs."""
    text = Text()
    elapsed = elapsed_by_id or {}
    for step in steps:
        label = clean_source_text(step.label)
        if step.state == "pending":
            text.append("◌ ", style="dim")
            text.append(label)
        elif step.state == "running":
            text.append(f"{running_glyph} ", style="#FFAF5F")
            text.append(label, style="bold")
            clock = elapsed.get(step.step_id, "")
            if clock:
                text.append(f"  {clock}", style="dim")
        elif step.state == "done":
            text.append("✓ ", style="#00D7AF")
            text.append(label, style="bold")
        elif step.state == "failed":
            text.append("✗ ", style="#FF5F5F")
            text.append(label, style="bold")
            if step.message:
                text.append("\n  " + clean_source_text(step.message), style="#FF5F5F")
            if step.hint:
                text.append("\n  " + clean_source_text(step.hint), style="dim")
        else:
            text.append("– ", style="dim")
            text.append(label, style="dim")
        text.append("\n")
    return text


def _render_raw_log(lines: Sequence[str], *, expanded: bool) -> Text:
    """Render the collapsible raw-log disclosure."""
    text = Text()
    if not lines:
        return text
    marker = "▾" if expanded else "▸"
    text.append(
        f"{marker} raw log ({len(lines)} line{'s' if len(lines) != 1 else ''})",
        style="dim",
    )
    if expanded:
        for line in lines[-_RAW_TAIL:]:
            text.append("\n" + clean_source_text(line), style="dim")
    return text


class NewProjectProgress(Vertical):
    """Live checklist fed by the durable ``project.add``/``project.create`` log."""

    can_focus = True
    BINDINGS = [
        ("space", "toggle_raw", "Raw log"),
    ]

    class ResultArrived(Message):
        """The reducer recorded a terminal onboarding result."""

        def __init__(self, result: ProgressResult) -> None:
            super().__init__()
            self.result = result

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._view = ProgressView()
        self._proc_id = ""
        self._log_path = ""
        self._seen_version: object | None = None
        self._tail_in_flight = False
        self._poll_timer: Any | None = None
        self._spinner_index = 0
        self._running_started: dict[str, float] = {}
        self._emitted_result: ProgressResult | None = None
        self._raw_expanded = False
        self._preview_glyph = "⠋"
        self._preview_elapsed = "3s"
        self._previewing = False
        self._tail_token: str | None = None
        self._settled = False
        self._settlement_tail_done = False
        self._operation = "project.add"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="new-project-progress-scroll"):
            yield Static(
                "SETUP",
                id="new-project-progress-heading",
                classes="new-project-card-heading",
            )
            yield Static("", id="new-project-progress-checklist", markup=False)
            yield Static("", id="new-project-progress-raw", markup=False)
        yield Static(
            "closing won't stop setup — it continues in Procs",
            id="new-project-progress-note",
            markup=False,
        )

    def on_unmount(self) -> None:
        self._stop_poll()
        self._unsubscribe_tail()
        cancel_pump_free_tasks(self)

    def attach_proc(self, proc_id: str, *, log_path: str = "") -> None:
        """Watch *proc_id* and start the 250 ms log-version poll."""
        self._proc_id = proc_id
        self._log_path = log_path
        self._seen_version = None
        self._emitted_result = None
        self._previewing = False
        self._settled = False
        self._settlement_tail_done = False
        self._view = ProgressView()
        self._running_started.clear()
        self._subscribe_tail()
        if self.is_mounted:
            self._paint()
            self._start_poll()
            self._poll_log()

    def set_operation(self, operation: str) -> None:
        """Record whether this run applies ``project.add`` or ``project.create``."""
        if operation in ("project.add", "project.create"):
            self._operation = operation

    def _verb(self) -> str:
        return "create" if self._operation == "project.create" else "add"

    def update_proc_id(self, old_id: str, new_id: str, *, log_path: str = "") -> None:
        """Follow the durable handle once the placeholder id is replaced."""
        if self._proc_id == old_id:
            self._proc_id = new_id
            if log_path:
                self._log_path = log_path
            self._seen_version = None
            self._subscribe_tail()

    def show_preview(
        self,
        view: ProgressView,
        *,
        running_glyph: str = "⠋",
        elapsed: str = "3s",
    ) -> None:
        """Paint a deterministic checklist for tests and PNG goldens."""
        self._previewing = True
        self._view = view
        self._preview_glyph = running_glyph
        self._preview_elapsed = elapsed
        self._stop_poll()
        if self.is_mounted:
            self._paint()

    def mark_initialized(self) -> None:
        """Add the completed init row after a successful hand-off."""
        self._settled = True
        self._stop_poll()
        self._unsubscribe_tail()
        self._view.mark_sase_initialized()
        if self.is_mounted:
            self._paint()

    def observe_completion(self, completion: TrackedProcCompletion[Any]) -> None:
        """Settle from durable completion when NDJSON never recorded a result."""
        if self._previewing or self._settled or self._emitted_result is not None:
            return
        if self._view.result is not None:
            self._handle_terminal_result(self._view.result)
            return
        if completion.success:
            return
        message = (
            completion.error or completion.message or f"Project {self._verb()} failed."
        )
        self._emit_failed_result(message)

    def current_view(self) -> ProgressView:
        """Return the live reducer state."""
        return self._view

    def action_toggle_raw(self) -> None:
        """Expand or collapse the raw-log disclosure."""
        if not self._view.raw_tail(80):
            return
        self._raw_expanded = not self._raw_expanded
        if self.is_mounted:
            self._paint()

    def on_click(self, event: events.Click) -> None:
        target = getattr(event, "control", None) or event.widget
        if getattr(target, "id", None) != "new-project-progress-raw":
            return
        self.action_toggle_raw()
        event.stop()

    def _subscribe_tail(self) -> None:
        self._unsubscribe_tail()
        proc_id = self._proc_id
        if not proc_id:
            return
        observer = getattr(self.app, "_proc_observer", None)
        subscribe = getattr(observer, "subscribe_tail", None)
        if callable(subscribe):
            self._tail_token = subscribe(proc_id)

    def _unsubscribe_tail(self) -> None:
        token = self._tail_token
        self._tail_token = None
        if token is None:
            return
        observer = getattr(self.app, "_proc_observer", None)
        unsubscribe = getattr(observer, "unsubscribe_tail", None)
        if callable(unsubscribe):
            unsubscribe(token)

    def _start_poll(self) -> None:
        self._stop_poll()
        self._poll_timer = self.set_interval(_POLL_SECONDS, self._poll_log)

    def _stop_poll(self) -> None:
        timer = self._poll_timer
        self._poll_timer = None
        if timer is not None:
            timer.stop()

    def _poll_log(self) -> None:
        if self._previewing:
            return
        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER)
        if any(step.state == "running" for step in self._view.checklist()):
            self._paint()
        if self._settled:
            return
        row = self._proc_row()
        settled = row is not None and not proc_status_is_active(str(row.status or ""))
        version, authoritative = self._version_token(row)
        if version is None:
            if not self._proc_id or self._view.result is not None:
                if self._view.result is not None:
                    self._handle_terminal_result(self._view.result)
                return
            version = ("pending", self._proc_id)
            authoritative = False
        if version == self._seen_version:
            if self._view.result is not None:
                self._handle_terminal_result(self._view.result)
                return
            if authoritative and not settled:
                return
            if settled and self._settlement_tail_done:
                self._fail_without_result(row)
                return
        if self._tail_in_flight:
            return
        self._seen_version = version
        self._tail_in_flight = True
        task = spawn_pump_free_task(
            self,
            self._read_tail(settled=settled),
            name=f"new-project-progress-tail:{self._proc_id}",
            registry_attr=_TASKS,
        )
        if task is None:
            self._tail_in_flight = False

    def _proc_row(self) -> Any | None:
        proc_id = self._proc_id
        if not proc_id:
            return None
        projection = getattr(self.app, "_effective_proc_projection", None)
        if not callable(projection):
            return None
        try:
            rows = projection().rows
        except Exception:
            return None
        for row in rows:
            if (
                row.proc_id == proc_id
                or getattr(row, "durable_proc_id", None) == proc_id
            ):
                path = getattr(row, "log_path", "") or ""
                if path:
                    self._log_path = path
                return row
        return None

    def _version_token(self, row: Any | None) -> tuple[object | None, bool]:
        if row is None:
            return None, False
        log = getattr(row, "log", None)
        raw_version = getattr(log, "version", None)
        version = int(raw_version) if raw_version is not None else 0
        token = (
            version,
            len(getattr(row, "output", "") or ""),
            getattr(row, "status", ""),
            getattr(row, "message", ""),
            getattr(row, "phase", "") or "",
            int(getattr(self.app, "_proc_generation", 0) or 0),
        )
        return token, version > 0

    async def _read_tail(self, *, settled: bool = False) -> None:
        proc_id = self._proc_id
        log_path = self._log_path
        try:
            text = await asyncio.to_thread(
                read_proc_log_tail,
                proc_id,
                DETAIL_LOG_LINES,
                log_path=log_path or None,
            )
        except Exception:
            text = ""
        self._tail_in_flight = False
        if not self.is_mounted or proc_id != self._proc_id or self._settled:
            return
        self._apply_text(text)
        if settled:
            self._settlement_tail_done = True
            if self._view.result is None and not self._settled:
                self._fail_without_result(self._proc_row())

    def _apply_text(self, text: str) -> None:
        if self._settled:
            return
        view = reduce_lines(text.splitlines())
        self._sync_running_clocks(view)
        self._view = view
        self._paint()
        result = view.result
        if result is not None and result != self._emitted_result:
            self._handle_terminal_result(result)

    def _handle_terminal_result(self, result: ProgressResult) -> None:
        if self._settled and self._emitted_result is not None:
            return
        self._settled = True
        self._stop_poll()
        self._unsubscribe_tail()
        if result != self._emitted_result:
            self._emitted_result = result
            self.post_message(self.ResultArrived(result))

    def _fail_without_result(self, row: Any | None) -> None:
        if self._settled or self._view.result is not None:
            if self._view.result is not None:
                self._handle_terminal_result(self._view.result)
            return
        message = f"Project {self._verb()} failed."
        if row is not None:
            message = str(
                getattr(row, "error", None) or getattr(row, "message", "") or message
            )
        self._emit_failed_result(message)

    def _emit_failed_result(self, message: str) -> None:
        result = ProgressResult(
            status="failed",
            project_key="",
            project_name="",
            next_argv=(),
            message=message,
        )
        self._view.result = result
        self._handle_terminal_result(result)

    def _sync_running_clocks(self, view: ProgressView) -> None:
        now = monotonic()
        running = {step.step_id for step in view.checklist() if step.state == "running"}
        for step_id in list(self._running_started):
            if step_id not in running:
                self._running_started.pop(step_id, None)
        for step_id in running:
            self._running_started.setdefault(step_id, now)

    def _elapsed_by_id(self) -> dict[str, str]:
        if self._previewing:
            return {
                step.step_id: self._preview_elapsed
                for step in self._view.checklist()
                if step.state == "running"
            }
        now = monotonic()
        return {
            step_id: format_elapsed(now - started)
            for step_id, started in self._running_started.items()
        }

    def _paint(self) -> None:
        glyph = (
            self._preview_glyph if self._previewing else _SPINNER[self._spinner_index]
        )
        self.query_one("#new-project-progress-checklist", Static).update(
            render_checklist(
                self._view.checklist(),
                running_glyph=glyph,
                elapsed_by_id=self._elapsed_by_id(),
            )
        )
        raw = self._view.raw_tail(80)
        self.set_class(bool(raw), "has-raw")
        self.query_one("#new-project-progress-raw", Static).update(
            _render_raw_log(raw, expanded=self._raw_expanded)
        )
        self.query_one("#new-project-progress-note", Static).update(
            Text(
                "closing won't stop setup — it continues in Procs",
                style="dim",
            )
        )


__all__ = [
    "NewProjectProgress",
    "format_elapsed",
    "render_checklist",
]
