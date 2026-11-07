"""Focused review and confirmation for an actionable ACE-run prune preview."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from sase.core.agent_artifact_run_prune_review import (
    RunPruneProjectAggregate,
    RunPruneReview,
    RunPruneReviewCounts,
    RunPruneSnapshot,
    RunPruneSnapshotItem,
    human_size,
)
from sase.core.time import local_now
from sase.notifications import Notification, load_notification_report

from ..models.artifact_run_prune_review_view import (
    build_artifact_run_prune_review_view,
)
from ._artifact_run_prune_recheck import (
    PRUNE_CONCURRENCY_KEY,
    prune_is_running,
    submit_run_prune_recheck,
)
from .notification_modal_palette import (
    PANE_ACCENT,
    PANE_ANSWERED,
    PANE_ERROR,
    PANE_MUTED,
    PANE_WARN,
)


class ArtifactRunPruneModal(ModalScreen[None]):
    """Show the captured prune plan and confirm a restorable quarantine."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("n", "cancel", "Cancel"),
        ("y", "confirm", "Move to trash"),
        ("r", "report", "Full report"),
        ("tab", "focus_next", "Next button"),
        ("shift+tab", "focus_previous", "Previous button"),
        ("right", "focus_next", "Next button"),
        ("down", "focus_next", "Next button"),
        ("left", "focus_previous", "Previous button"),
        ("up", "focus_previous", "Previous button"),
    ]

    def __init__(
        self,
        review: RunPruneReview,
        notification: Notification,
        *,
        now: datetime | None = None,
    ) -> None:
        super().__init__()
        self._review = review
        self._notification = notification
        self._now = now or local_now()
        self._display_snapshot: Mapping[str, str] = {}
        self._snapshot_exists: bool | None = None
        self._grace_days: int | None = None
        self._is_running = False
        self._view = build_artifact_run_prune_review_view(
            review,
            self._display_snapshot,
            now=self._now,
            snapshot_exists=None,
        )

    def compose(self) -> ComposeResult:
        with Container(
            id="prune-review-container",
            classes="prune-review-panel prune-review--checking",
        ):
            yield Static(self._title(), id="prune-review-title")
            yield Static(self._view.freshness, id="prune-review-freshness")
            with VerticalScroll(id="prune-review-scroll"):
                yield Static(self._hero(), id="prune-review-hero")
                yield Static(self._view.keep_window, id="prune-review-window")
                yield Static(self._project_table(68), id="prune-review-projects")
                yield Static(self._state_banner(), id="prune-review-state")
                yield Static(
                    self._consequence_text(),
                    id="prune-review-consequence",
                )
            with Horizontal(id="prune-review-buttons"):
                yield Button(
                    self._confirm_label(),
                    id="prune-review-move",
                    variant="warning",
                    disabled=True,
                )
                yield Button("Cancel", id="prune-review-cancel")
            yield Static(
                self._footer_text(),
                id="prune-review-footer",
            )

    def on_mount(self) -> None:
        self._is_running = prune_is_running(self.app)
        self._refresh_render()
        self.call_after_refresh(self._focus_cancel)
        from sase.ace.tui.util.pump_tasks import spawn_pump_free_task

        spawn_pump_free_task(
            self,
            self._load_snapshot_state(),
            name=f"artifact-run-prune-review:{self._review.fingerprint}",
            registry_attr="_prune_review_tasks",
        )

    def on_unmount(self) -> None:
        from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks

        cancel_pump_free_tasks(self)

    async def _load_snapshot_state(self) -> None:
        """Load the checked snapshot and display-name cache off the message pump."""
        from sase.core.agent_artifact_run_prune_review import load_snapshot
        from sase.project_display_names import (
            ProjectDisplaySnapshot,
            cached_project_display_snapshot,
        )

        def load() -> tuple[bool, Mapping[str, str], int]:
            from sase.config import get_artifact_retention_trash_grace_days

            try:
                snapshot = load_snapshot(self._review.fingerprint)
            except Exception:
                snapshot = None
            try:
                display_snapshot = cached_project_display_snapshot()
            except Exception:
                display_snapshot = ProjectDisplaySnapshot()
            try:
                grace_days = get_artifact_retention_trash_grace_days()
            except Exception:
                grace_days = 14
            return (
                _snapshot_matches_review(snapshot, self._review),
                display_snapshot,
                grace_days,
            )

        snapshot_exists, display_snapshot, grace_days = await asyncio.to_thread(load)
        if not self.is_mounted:
            return
        self._snapshot_exists = snapshot_exists
        self._display_snapshot = display_snapshot
        self._grace_days = grace_days
        # Proc projections can change while the background snapshot check runs.
        self._is_running = prune_is_running(self.app)
        self._refresh_render()

    def _title(self) -> Text:
        title = Text("🧹 Prune old ACE runs", style=f"bold {PANE_ACCENT}")
        if self._view.stale:
            title.stylize(f"bold {PANE_WARN}")
        return title

    def _hero(self) -> Text:
        hero = Text()
        hero.append(self._view.run_count, style=f"bold {PANE_ACCENT}")
        hero.append(f" {_run_word(self._review.counts.selected)}      ")
        hero.append(self._view.reclaimable_size, style=f"bold {PANE_ACCENT}")
        hero.append("      ")
        hero.append(self._view.project_count, style=f"bold {PANE_ACCENT}")
        hero.append(" projects")
        return hero

    def _move_label(self) -> str:
        count = self._review.counts.selected
        return f"🧹 Move {count:,} {_run_word(count)} to trash"

    def _confirm_label(self) -> str:
        state = self._view.state
        if state == "BLOCKED":
            return "↻ Re-check protections"
        if state == "SNAPSHOT_MISSING":
            return "↻ Refresh preview"
        return self._move_label()

    def _footer_text(self) -> str:
        state = self._view.state
        if state == "READY":
            return "y move to trash · r full report · n/esc cancel"
        if state in {"BLOCKED", "SNAPSHOT_MISSING"}:
            return "y re-check now · r full report · n/esc cancel"
        return "r full report · n/esc cancel"

    def _project_table(self, width: int) -> Group:
        wide = width >= 96
        project_width = min(34, max(12, width - 70)) if wide else max(8, width - 56)
        runs_width, size_width, bar_width, span_width = (
            (8, 10, 20, 18) if wide else (7, 9, 8, 14)
        )
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(
            "PROJECT", width=project_width, no_wrap=True, overflow="ellipsis"
        )
        table.add_column("RUNS", width=runs_width, justify="right", no_wrap=True)
        table.add_column("SIZE", width=size_width, justify="right", no_wrap=True)
        table.add_column("", width=bar_width, no_wrap=True)
        table.add_column("SPAN", width=span_width, justify="right", no_wrap=True)
        table.add_row(
            Text("PROJECT", style="bold dim"),
            Text("RUNS", style="bold dim"),
            Text("SIZE", style="bold dim"),
            Text(""),
            Text("SPAN", style="bold dim"),
        )
        for project in self._view.projects:
            filled = round(project.bar_fraction * bar_width)
            bar = "█" * filled + "░" * max(0, bar_width - filled)
            table.add_row(
                project.label,
                f"{project.runs:,}",
                project.size_label,
                Text(bar, style=PANE_ACCENT),
                project.span,
            )
        return Group(table)

    def _state_banner(self) -> Group:
        state = self._view.state
        message: Text
        if state == "BLOCKED":
            message = Text(
                "⚠ Protection sources are unreadable; nothing can be pruned.",
                style=f"bold {PANE_ERROR}",
            )
            if self._view.unavailable_sources:
                for source in self._view.unavailable_sources:
                    message.append(f"\n  {source}", style=PANE_ERROR)
            remaining = self._view.unavailable_source_count - len(
                self._view.unavailable_sources
            )
            if remaining > 0:
                message.append(f"\n  +{remaining} more", style=PANE_ERROR)
            elif not self._view.unavailable_sources:
                message.append(
                    "\nProtection evidence is unavailable.",
                    style=PANE_ERROR,
                )
            message.append(
                "\nPress y to re-check now; the hourly preview also re-checks.",
                style=PANE_MUTED,
            )
        elif state == "SNAPSHOT_MISSING":
            message = Text(
                "This preview is no longer available. Press y to refresh it now, "
                "or wait for the next hourly preview.",
                style=f"bold {PANE_WARN}",
            )
        elif state == "RUNNING":
            message = Text(
                "A prune or re-check is already running.",
                style=f"bold {PANE_WARN}",
            )
        elif state == "READY":
            message = Text(
                "✓ Protections will be re-checked before each run moves.",
                style=f"bold {PANE_ANSWERED}",
            )
        else:
            message = Text("Checking this preview…", style=f"italic {PANE_MUTED}")

        renderables: list[Text] = [message]
        if self._view.stale_warning:
            renderables.append(
                Text(self._view.stale_warning, style=f"bold {PANE_WARN}")
            )
        if self._view.more_projects:
            renderables.append(
                Text(
                    f"+{self._view.more_projects} more projects",
                    style=f"italic {PANE_MUTED}",
                )
            )
        return Group(*renderables)

    def _refresh_render(self) -> None:
        self._view = build_artifact_run_prune_review_view(
            self._review,
            self._display_snapshot,
            now=self._now,
            snapshot_exists=self._snapshot_exists,
            is_running=self._is_running,
        )
        try:
            self.query_one("#prune-review-title", Static).update(self._title())
            self.query_one("#prune-review-freshness", Static).update(
                self._view.freshness
            )
            self.query_one("#prune-review-hero", Static).update(self._hero())
            self.query_one("#prune-review-window", Static).update(
                self._view.keep_window
            )
            scroll = self.query_one("#prune-review-scroll", VerticalScroll)
            width = scroll.scrollable_content_region.width or self.size.width - 12
            self.query_one("#prune-review-projects", Static).update(
                self._project_table(width)
            )
            self.query_one("#prune-review-state", Static).update(self._state_banner())
            self.query_one("#prune-review-consequence", Static).update(
                self._consequence_text()
            )
            move = self.query_one("#prune-review-move", Button)
            move.label = self._confirm_label()
            confirmable = self._view.state in {
                "READY",
                "BLOCKED",
                "SNAPSHOT_MISSING",
            }
            move.disabled = not confirmable
            if self._view.state == "READY":
                move.variant = "warning"
            elif confirmable:
                move.variant = "primary"
            else:
                move.variant = "default"
            self.query_one("#prune-review-footer", Static).update(self._footer_text())
            panel = self.query_one("#prune-review-container", Container)
            for state in (
                "checking",
                "ready",
                "blocked",
                "snapshot_missing",
                "running",
            ):
                panel.set_class(
                    self._view.state.lower() == state, f"prune-review--{state}"
                )
        except Exception:
            # compose has not mounted the widgets yet; the initial values above
            # are already valid and on_mount performs the first full refresh.
            return

    def _consequence_text(self) -> str:
        days = 14 if self._grace_days is None else self._grace_days
        return (
            "Archived agent records stay listed; pruned run directories "
            f"remain restorable for {days} days."
        )

    def _focus_cancel(self) -> None:
        try:
            self.query_one("#prune-review-cancel", Button).focus()
        except Exception:
            return

    def _focus_button(self, direction: int) -> None:
        buttons = [
            button
            for button in self.query(Button)
            if button.display and not button.disabled
        ]
        if not buttons:
            return
        current = next((i for i, button in enumerate(buttons) if button.has_focus), 0)
        buttons[(current + direction) % len(buttons)].focus()

    def action_focus_next(self) -> None:
        self._focus_button(1)

    def action_focus_previous(self) -> None:
        self._focus_button(-1)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_report(self) -> None:
        report = load_notification_report(self._notification)
        if report is None or report.document is None:
            reason = report.error if report is not None else None
            self.app.notify(
                f"Unable to open report: {reason or 'report could not be loaded'}",
                severity="warning",
            )
            return
        from .report_modal import ReportModal

        self.app.push_screen(ReportModal(report))

    def action_confirm(self) -> None:
        state = self._view.state
        if state == "CHECKING":
            self.app.notify(
                "Still checking this preview — try again in a moment.",
                severity="warning",
            )
            return
        if state == "RUNNING":
            self.app.notify(
                "ACE run pruning is already running.",
                severity="warning",
            )
            return
        if state in {"BLOCKED", "SNAPSHOT_MISSING"}:
            submit_run_prune_recheck(self)
            return
        if state != "READY":
            return
        if prune_is_running(self.app):
            self._is_running = True
            self._refresh_render()
            self.app.notify("ACE run pruning is already running", severity="warning")
            return
        submit = getattr(self.app, "_submit_durable_proc", None)
        if not callable(submit):
            self.app.notify("Durable prune queue is unavailable", severity="error")
            return

        from sase.ace.tui.actions._durable_ops import (
            durable_fingerprint,
            durable_request_payload,
            sase_argv,
        )
        from sase.ops.names import ARTIFACT_PRUNE_RUNS

        fingerprint = self._review.fingerprint
        proc = submit(
            sase_argv(
                "artifact",
                "prune-runs",
                "--apply",
                "--snapshot",
                fingerprint,
                "--notify",
                "--json",
            ),
            operation=ARTIFACT_PRUNE_RUNS,
            request=durable_request_payload(snapshot=fingerprint),
            request_fingerprint=durable_fingerprint(ARTIFACT_PRUNE_RUNS, fingerprint),
            concurrency_keys=(PRUNE_CONCURRENCY_KEY,),
            label="Prune ACE runs",
            display_name="Prune ACE runs",
            duplicate_message="ACE run pruning is already running",
            on_complete=self._on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        if proc is None:
            return
        self.app.notify(
            f"🧹 Moving {self._review.counts.selected:,} ACE "
            f"{_run_word(self._review.counts.selected)} to trash — "
            "re-verifying protections first",
            severity="information",
        )
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "prune-review-move":
            self.action_confirm()
        elif event.button.id == "prune-review-cancel":
            self.action_cancel()

    def _on_complete(self, completion: object) -> None:
        payload = getattr(completion, "payload", None)
        success = bool(getattr(completion, "success", False))
        if isinstance(payload, Mapping) and payload.get("blocked_reason"):
            success = False
        if success:
            fields = payload if isinstance(payload, Mapping) else {}
            moved = _as_count(fields.get("quarantined"), self._review.counts.selected)
            moved_bytes = _as_count(fields.get("bytes"), self._review.reclaimable_bytes)
            kept = _as_count(fields.get("kept"), 0)
            until = _short_date(fields.get("restorable_until"))
            message = (
                f"🧹 Moved {moved:,} ACE {_run_word(moved)} to trash · "
                f"{human_size(moved_bytes)}"
            )
            if until:
                message += f" · restorable until {until}"
            message += f" · {kept:,} kept"
            index_errors = fields.get("index_errors") or ()
            if isinstance(index_errors, list | tuple) and index_errors:
                message += f" · {len(index_errors)} index error(s)"
                self.app.notify(message, severity="warning")
            else:
                self.app.notify(message, severity="information")
        else:
            fields = payload if isinstance(payload, Mapping) else {}
            reason = (
                fields.get("blocked_reason")
                or getattr(completion, "error", None)
                or getattr(completion, "message", None)
                or "the prune did not complete"
            )
            self.app.notify(
                f"🧹 Preview kept; {reason}. See the proc log.",
                severity="error",
            )
        refresh = getattr(self.app, "_refresh_notification_count", None)
        if callable(refresh):
            refresh()


def _snapshot_matches_review(
    snapshot: RunPruneSnapshot | None,
    review: RunPruneReview,
) -> bool:
    """Reject an existing snapshot whose candidates differ from its preview."""
    counts: RunPruneReviewCounts = review.counts
    if snapshot is None or snapshot.fingerprint != review.fingerprint:
        return False
    if snapshot.keep_recent_months != review.keep_recent_months:
        return False
    if len(snapshot.items) != counts.selected:
        return False
    if sum(item.size_bytes for item in snapshot.items) != review.reclaimable_bytes:
        return False
    if snapshot.empty_shard_count != counts.empty_shards:
        return False
    if len(snapshot.sources_unavailable) != review.unavailable_source_count:
        return False
    if snapshot.sources_unavailable[: len(review.unavailable_sources)] != (
        review.unavailable_sources
    ):
        return False

    items_by_project: dict[str, list[RunPruneSnapshotItem]] = {}
    for item in snapshot.items:
        items_by_project.setdefault(item.project, []).append(item)
    expected_projects: dict[str, RunPruneProjectAggregate] = {
        project.project: project for project in review.projects
    }
    if len(expected_projects) != len(review.projects):
        return False
    if items_by_project.keys() != expected_projects.keys():
        return False
    for project_key, items in items_by_project.items():
        expected = expected_projects[project_key]
        if (
            len(items) != expected.runs
            or sum(item.size_bytes for item in items) != expected.bytes
            or min(item.timestamp for item in items) != expected.oldest
            or max(item.timestamp for item in items) != expected.newest
        ):
            return False
    return True


def _as_count(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    return default


def _run_word(count: int) -> str:
    return "run" if count == 1 else "runs"


def _short_date(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        date = datetime.fromisoformat(value)
    except ValueError:
        return value
    return f"{date.strftime('%b')} {date.day}"


__all__ = ["ArtifactRunPruneModal"]
