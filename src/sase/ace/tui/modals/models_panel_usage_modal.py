"""Read-only Providers · Usage view: cached first paint, durable updates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import DataTable, OptionList, Static
from textual.widgets._option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.tui.proc_observer import proc_projection_for
from sase.llm_provider.usage import (
    PROVIDER_USAGE_REFRESH_JOINED,
    PROVIDER_USAGE_REFRESH_RESERVED,
)
from sase.llm_provider.usage.refresh import (
    UsageRefreshReceipt,
    eligible_usage_providers,
    submit_usage_refresh,
)

from .base import OptionListNavigationMixin
from .models_panel_duration import now as _now
from .models_panel_usage_rendering import (
    detail_columns_for_width,
    provider_detail_header,
    provider_summary_text,
    usage_view_width_tier,
    window_detail_row,
)
from .models_panel_usage_state import (
    ProviderUsageViewSnapshot,
    load_usage_view_snapshot,
)

_STARTED_REFRESH_STATUSES = frozenset(
    (PROVIDER_USAGE_REFRESH_RESERVED, PROVIDER_USAGE_REFRESH_JOINED)
)
_FOOTER_TEXT = (
    "[green]enter[/green]=Details  "
    "[green]u[/green]=Update usage  "
    "[bold #FFAF5F]⚠[/bold #FFAF5F]=Collector failing  "
    "[dim]tab[/dim]=Focus  "
    "[dim]j/k[/dim]=Navigate  "
    "[dim]esc[/dim]=Close"
)
_DETAIL_TABLE_ID = "provider-usage-detail"
_OPTION_LIST_ID = "provider-usage-list"


def _usage_refresh_scope(provider: str) -> str:
    return f"usage-refresh:{provider}"


class ProviderUsageModal(OptionListNavigationMixin, ModalScreen[None]):
    """Read-only subscription usage: cached first paint, `u` to update."""

    _option_list_id = _OPTION_LIST_ID

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("q", "cancel", "Close"),
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("ctrl+n", "next_option", "Next"),
        ("ctrl+p", "prev_option", "Previous"),
        ("enter", "open_details", "Details"),
        ("u", "update_usage", "Update usage"),
    ]

    def __init__(
        self,
        snapshot: ProviderUsageViewSnapshot | None = None,
        *,
        load_snapshot: Callable[
            [], ProviderUsageViewSnapshot
        ] = load_usage_view_snapshot,
        initial_provider: str | None = None,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._load_snapshot = load_snapshot
        self._initial_provider = initial_provider
        self._snapshot_worker: Worker[ProviderUsageViewSnapshot] | None = None
        self._snapshot_keep: str | None = None
        self._scan_conflicts_on_load = True
        self._summary_after_load: tuple[str, ...] | None = None
        self._update_worker: Worker[UsageRefreshReceipt] | None = None
        self._pending: dict[str, str] = {}
        self._clock_timer: Timer | None = None
        self._poll_timer: Timer | None = None
        self._detail_width_tier: str | None = None

    def compose(self) -> ComposeResult:
        with Container(id="provider-usage-container"):
            yield Static("Providers · Usage", id="provider-usage-title")
            yield Static("", id="provider-usage-summary")
            yield OptionList(id=_OPTION_LIST_ID)
            yield Static("", id="provider-usage-header")
            yield DataTable(id=_DETAIL_TABLE_ID)
            yield Static(_FOOTER_TEXT, id="provider-usage-footer")

    def on_mount(self) -> None:
        table = self.query_one(f"#{_DETAIL_TABLE_ID}", DataTable)
        table.cursor_type = "row"
        self._apply_detail_columns()
        if self._snapshot is not None:
            self._render_rows()
        else:
            self._show_loading()
        self.query_one(f"#{_OPTION_LIST_ID}", OptionList).focus()
        self._start_snapshot_load(keep_provider=self._initial_provider)
        self._clock_timer = self.set_interval(5.0, self._refresh_clock)

    def on_unmount(self) -> None:
        for timer in (self._clock_timer, self._poll_timer):
            if timer is not None:
                timer.stop()
        for worker in (self._snapshot_worker, self._update_worker):
            if worker is not None and not worker.is_finished:
                worker.cancel()

    def on_resize(self) -> None:
        if self._apply_detail_columns():
            self._render_rows()

    def _render_width(self) -> int:
        return self.size.width or 120

    def _apply_detail_columns(self) -> bool:
        """(Re)build detail-table columns if the width tier changed.

        Returns whether a rebuild happened, so callers know row data must be
        repopulated to match the new column count.
        """
        tier = usage_view_width_tier(self._render_width())
        if tier == self._detail_width_tier:
            return False
        self._detail_width_tier = tier
        table = self.query_one(f"#{_DETAIL_TABLE_ID}", DataTable)
        table.clear(columns=True)
        table.add_columns(*detail_columns_for_width(self._render_width()))
        return True

    # --- actions ---------------------------------------------------------

    def action_open_details(self) -> None:
        try:
            self.query_one(f"#{_DETAIL_TABLE_ID}", DataTable).focus()
        except Exception:
            return

    def action_update_usage(self) -> None:
        if self._update_worker is not None and not self._update_worker.is_finished:
            self.notify("A usage update is already running.", severity="warning")
            return

        def task() -> UsageRefreshReceipt:
            return submit_usage_refresh(None, explicit=True, origin="ace")

        self._update_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            exit_on_error=False,
            group="provider-usage-update",
        )

    # --- snapshot loading --------------------------------------------------

    def _show_loading(self) -> None:
        option_list = self.query_one(f"#{_OPTION_LIST_ID}", OptionList)
        option_list.clear_options()
        option_list.add_option(
            Option(
                Text("Loading cached usage…", style="dim"),
                id="__loading__",
                disabled=True,
            )
        )

    def _start_snapshot_load(
        self,
        *,
        keep_provider: str | None = None,
        scan_conflicts: bool = True,
        summary_after: tuple[str, ...] | None = None,
    ) -> None:
        if self._snapshot_worker is not None and not self._snapshot_worker.is_finished:
            self._snapshot_worker.cancel()

        def task() -> ProviderUsageViewSnapshot:
            return self._load_snapshot()

        self._snapshot_keep = keep_provider
        self._scan_conflicts_on_load = scan_conflicts
        self._summary_after_load = summary_after
        self._snapshot_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            exit_on_error=False,
            group="provider-usage-snapshot",
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._snapshot_worker:
            self._on_snapshot_worker(event)
        elif event.worker is self._update_worker:
            self._on_update_worker(event)

    def _on_snapshot_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        keep = self._snapshot_keep
        scan_conflicts = self._scan_conflicts_on_load
        summary_after = self._summary_after_load
        self._snapshot_worker = None
        self._snapshot_keep = None
        self._summary_after_load = None
        if event.state == WorkerState.ERROR:
            self.notify(
                f"Could not load cached usage: {event.worker.error}",
                severity="warning",
            )
            return
        snapshot = event.worker.result
        if snapshot is None:
            return
        self._snapshot = snapshot
        self._render_rows(keep_provider=keep)
        if snapshot.load_error:
            self.notify(
                f"Cached usage store is unreadable: {snapshot.load_error}",
                severity="warning",
            )
        if scan_conflicts:
            self._attach_in_flight_refreshes()
        if summary_after is not None:
            self._notify_update_summary(summary_after)

    def _attach_in_flight_refreshes(self) -> None:
        """Show `Updating` for providers whose durable refresh is still live.

        A previous `u` press may still be running in a supervised proc after
        this screen was closed and reopened; this is a read-only scope check,
        never a new submission.
        """
        candidates = (
            {str(item.get("provider") or "") for item in self._snapshot.providers}
            if self._snapshot
            else set()
        )
        candidates.update(eligible_usage_providers())
        candidates.discard("")
        if not candidates:
            return
        projection = proc_projection_for(self.app)
        started = {}
        for provider in candidates:
            conflict = projection.scope_conflict((_usage_refresh_scope(provider),))
            if conflict is not None:
                started[provider] = conflict.proc_id
        if started:
            self._begin_tracking(started)

    # --- update tracking ----------------------------------------------------

    def _on_update_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        self._update_worker = None
        if event.state == WorkerState.ERROR:
            self.notify(
                f"Could not request a usage update: {event.worker.error}",
                severity="error",
            )
            return
        receipt = event.worker.result
        if receipt is None:
            return
        started = {
            item.provider: item.operation_id
            for item in receipt.providers
            if item.operation_id and item.status in _STARTED_REFRESH_STATUSES
        }
        if not started:
            self.notify("No eligible providers to update.", severity="warning")
            return
        self._begin_tracking(started)

    def _begin_tracking(self, operations: Mapping[str, str]) -> None:
        self._pending.update(operations)
        self._render_rows()
        if self._poll_timer is None:
            self._poll_timer = self.set_interval(1.0, self._poll_pending)

    def _poll_pending(self) -> None:
        if not self._pending:
            if self._poll_timer is not None:
                self._poll_timer.stop()
                self._poll_timer = None
            return
        projection = proc_projection_for(self.app)
        still_pending: dict[str, str] = {}
        for provider, operation_id in self._pending.items():
            conflict = projection.scope_conflict((_usage_refresh_scope(provider),))
            if conflict is not None and conflict.proc_id == operation_id:
                still_pending[provider] = operation_id
        finished = tuple(sorted(set(self._pending) - set(still_pending)))
        self._pending = still_pending
        if not finished:
            return
        if not self._pending and self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        # Drop the `Updating` annotation immediately; the reload below fills
        # in the actual post-refresh values once it completes.
        self._render_rows()
        self._start_snapshot_load(
            keep_provider=self._highlighted_provider(),
            scan_conflicts=False,
            summary_after=finished,
        )

    def _notify_update_summary(self, providers: tuple[str, ...]) -> None:
        by_name = (
            {str(item.get("provider") or ""): item for item in self._snapshot.providers}
            if self._snapshot
            else {}
        )
        failed = [
            name
            for name in providers
            if str(by_name.get(name, {}).get("collection_status") or "")
            in {"error", "unauthenticated"}
        ]
        ok = [name for name in providers if name not in failed]
        parts = []
        if ok:
            parts.append(f"{len(ok)} updated")
        if failed:
            parts.append(f"{len(failed)} failed ({', '.join(sorted(failed))})")
        self.notify(
            "Usage update: " + ", ".join(parts) if parts else "Usage update finished.",
            severity="warning" if failed else "information",
        )

    # --- rendering -----------------------------------------------------------

    def _render_rows(self, *, keep_provider: str | None = None) -> None:
        option_list = self.query_one(f"#{_OPTION_LIST_ID}", OptionList)
        keep = (
            keep_provider if keep_provider is not None else self._highlighted_provider()
        )
        option_list.clear_options()
        providers = self._snapshot.providers if self._snapshot is not None else ()
        if not providers:
            option_list.add_option(
                Option(
                    Text("No observations yet; press u to update usage.", style="dim"),
                    id="__empty__",
                    disabled=True,
                )
            )
        else:
            width = self._render_width()
            for provider in providers:
                name = str(provider.get("provider") or "")
                option_list.add_option(
                    Option(
                        provider_summary_text(
                            provider, updating=name in self._pending, width=width
                        ),
                        id=name,
                    )
                )
        self._restore_highlight(option_list, keep)
        self._update_detail()

    def _restore_highlight(
        self, option_list: OptionList, preferred: str | None
    ) -> None:
        if preferred is not None:
            try:
                index = option_list.get_option_index(preferred)
                if not option_list.get_option_at_index(index).disabled:
                    option_list.highlighted = index
                    return
            except Exception:
                pass
        for index in range(option_list.option_count):
            if not option_list.get_option_at_index(index).disabled:
                option_list.highlighted = index
                return

    def _highlighted_provider(self) -> str | None:
        try:
            option_list = self.query_one(f"#{_OPTION_LIST_ID}", OptionList)
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        provider = str(option.id) if option.id is not None else ""
        return provider or None

    def _selected_provider(self) -> Mapping[str, Any] | None:
        name = self._highlighted_provider()
        if name is None or self._snapshot is None:
            return None
        for provider in self._snapshot.providers:
            if str(provider.get("provider") or "") == name:
                return provider
        return None

    def _update_detail(self) -> None:
        self._apply_detail_columns()
        table = self.query_one(f"#{_DETAIL_TABLE_ID}", DataTable)
        table.clear()
        header = self.query_one("#provider-usage-header", Static)
        provider = self._selected_provider()
        if provider is None:
            header.update("")
            return
        now = _now()
        width = self._render_width()
        header.update(provider_detail_header(provider, now=now))
        windows = provider.get("windows")
        rows = (
            [w for w in windows if isinstance(w, Mapping)]
            if isinstance(windows, list)
            else []
        )
        column_count = len(detail_columns_for_width(width))
        if not rows:
            table.add_row("No windows observed", *(["-"] * (column_count - 1)))
        for window in rows:
            table.add_row(*window_detail_row(window, now=now, width=width))

    def _refresh_clock(self) -> None:
        if self._snapshot is not None and self._snapshot.providers:
            self._render_rows()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        self._update_detail()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        # OptionList's own `enter` binding fires `action_select`/this message
        # before the screen's `enter` binding would ever see the keypress.
        event.stop()
        self.action_open_details()


__all__ = ["ProviderUsageModal"]
