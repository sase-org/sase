"""Refresh panel single-key chooser modal."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from rich.cells import cell_len
from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static
from textual.worker import Worker, WorkerState

from sase.llm_provider.usage.config import get_usage_metrics_settings
from sase.llm_provider.usage.presentation import age_label
from sase.llm_provider.usage.refresh import eligible_usage_providers

from .models_panel_usage_state import load_usage_view_snapshot

type RefreshChoice = Literal["this_tab", "full_history", "usage", "everything"]

_CHECKING_CHIP = "checking…"
_ROW_WIDTH = 68
_FOOTER = "  [dim]r tab · f history · u usage · a all · esc[/]"
_USAGE_DISABLED_REASON = "subscription usage collection is disabled"
_USAGE_NO_PROVIDERS_REASON = "No eligible providers."


@dataclass(frozen=True)
class RefreshRow:
    """One option in the Refresh panel chooser."""

    choice: RefreshChoice
    key: str
    aliases: tuple[str, ...]
    title: str
    target: str
    subtitle: str
    chip: str
    tone: str = ""
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class UsageRowStatus:
    """Worker result that patches the usage row after first paint."""

    provider_count: int
    chip: str
    unavailable_reason: str | None


def _load_refresh_usage_status() -> UsageRowStatus:
    """Load usage-row availability and freshness off the UI thread."""
    if not get_usage_metrics_settings().enabled:
        return UsageRowStatus(
            provider_count=0,
            chip="",
            unavailable_reason=_USAGE_DISABLED_REASON,
        )
    providers = eligible_usage_providers()
    if not providers:
        return UsageRowStatus(
            provider_count=0,
            chip="",
            unavailable_reason=_USAGE_NO_PROVIDERS_REASON,
        )
    snapshot = load_usage_view_snapshot()
    newest = _newest_usage_window(snapshot.providers)
    return UsageRowStatus(
        provider_count=len(providers),
        chip=age_label(newest) if newest is not None else "unknown",
        unavailable_reason=None,
    )


def _newest_usage_window(
    providers: tuple[Mapping[str, Any], ...],
) -> Mapping[str, Any] | None:
    newest: Mapping[str, Any] | None = None
    newest_age: float | None = None
    for provider in providers:
        windows = provider.get("windows")
        if not isinstance(windows, list):
            continue
        for window in windows:
            if not isinstance(window, Mapping):
                continue
            age = window.get("age_seconds")
            if not isinstance(age, int | float):
                continue
            age_value = float(age)
            if newest_age is None or age_value < newest_age:
                newest_age = age_value
                newest = window
    return newest


class RefreshPanelModal(ModalScreen[RefreshChoice | None]):
    """Single-key chooser for ACE refresh targets."""

    AUTO_FOCUS = ""

    BINDINGS = [
        Binding("r", "choose_this_tab", "This tab", show=False),
        Binding("R", "choose_this_tab", "This tab", show=False),
        Binding("1", "choose_this_tab", "This tab", show=False),
        Binding("f", "choose_full_history", "Full history", show=False),
        Binding("2", "choose_full_history", "Full history", show=False),
        Binding("u", "choose_usage", "Usage windows", show=False),
        Binding("3", "choose_usage", "Usage windows", show=False),
        Binding("a", "choose_everything", "Everything", show=False),
        Binding("4", "choose_everything", "Everything", show=False),
        Binding("enter", "select_cursor", "Select", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("ctrl+n", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("ctrl+p", "cursor_up", "Up", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        *,
        tab_label: str,
        rows: tuple[RefreshRow, ...],
        auto_refresh_label: str | None = None,
        initial_choice: RefreshChoice = "this_tab",
        banner: str | None = None,
        load_usage_status: Callable[[], UsageRowStatus] = _load_refresh_usage_status,
    ) -> None:
        super().__init__()
        self.tab_label = tab_label
        self._rows = list(rows)
        self._auto_refresh_label = auto_refresh_label
        self._banner = banner
        self._load_usage_status = load_usage_status
        self._cursor = _cursor_index(self._rows, initial_choice)
        self._usage_worker: Worker[UsageRowStatus] | None = None
        self._usage_loaded = False

    def compose(self) -> ComposeResult:
        with Container(
            id="refresh-panel-container",
            classes="duration-choice-container",
        ):
            with Vertical(
                id="refresh-panel-body",
                classes="duration-choice-body",
            ):
                yield Label(
                    "Refresh",
                    id="refresh-panel-title",
                    classes="duration-choice-title",
                )
                if self._auto_refresh_label is not None:
                    yield Static(
                        f"  [dim]{escape(self._auto_refresh_label)}[/]",
                        id="refresh-panel-header",
                        classes="refresh-panel-header duration-choice-row",
                    )
                if self._banner is not None:
                    yield Static(
                        f"  [dim]{escape(self._banner)}[/]",
                        id="refresh-panel-banner",
                        classes="refresh-panel-header duration-choice-row",
                    )
                for index, row in enumerate(self._rows):
                    yield Static(
                        self._render_row(self._row_for_display(row)),
                        id=f"refresh-panel-row-{row.choice}",
                        classes=self._row_classes(row, selected=index == self._cursor),
                    )
                yield Static(
                    "",
                    classes="refresh-panel-spacer duration-choice-spacer",
                )
                yield Static(
                    _FOOTER,
                    id="refresh-panel-footer",
                    classes="refresh-panel-footer duration-choice-row",
                )

    def on_mount(self) -> None:
        self._usage_worker = self.run_worker(
            self._load_usage_status,
            thread=True,
            exit_on_error=False,
        )

    def on_unmount(self) -> None:
        worker = self._usage_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._usage_worker:
            return
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        self._usage_worker = None
        if event.state != WorkerState.SUCCESS:
            return
        status = event.worker.result
        if isinstance(status, UsageRowStatus):
            self._apply_usage_status(status)

    def action_choose_this_tab(self) -> None:
        """Choose the current-tab refresh."""
        self._choose("this_tab")

    def action_choose_full_history(self) -> None:
        """Choose the Agents full-history rescan."""
        self._choose("full_history")

    def action_choose_usage(self) -> None:
        """Choose the provider usage-window refresh."""
        self._choose("usage")

    def action_choose_everything(self) -> None:
        """Choose the everything sweep."""
        self._choose("everything")

    def action_select_cursor(self) -> None:
        """Activate the row under the cursor."""
        if not self._rows:
            return
        self._choose(self._rows[self._cursor].choice)

    def action_cursor_down(self) -> None:
        """Move the cursor down, wrapping at the last row."""
        self._move_cursor(1)

    def action_cursor_up(self) -> None:
        """Move the cursor up, wrapping at the first row."""
        self._move_cursor(-1)

    def action_cancel(self) -> None:
        """Close without choosing a refresh."""
        self.dismiss(None)

    def _choose(self, choice: RefreshChoice) -> None:
        row = self._row_for_choice(choice)
        if row is None:
            return
        if row.unavailable_reason:
            self.notify(row.unavailable_reason, severity="warning")
            return
        self.dismiss(choice)

    def _move_cursor(self, delta: int) -> None:
        if not self._rows:
            return
        self._cursor = (self._cursor + delta) % len(self._rows)
        self._refresh_rows()

    def _apply_usage_status(self, status: UsageRowStatus) -> None:
        self._usage_loaded = True
        for index, row in enumerate(self._rows):
            if row.choice != "usage":
                continue
            self._rows[index] = replace(
                row,
                chip=status.chip,
                target=_usage_target(status, row),
                unavailable_reason=status.unavailable_reason,
            )
            break
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        if not self.is_mounted:
            return
        for index, row in enumerate(self._rows):
            widget = self.query_one(f"#refresh-panel-row-{row.choice}", Static)
            widget.update(self._render_row(self._row_for_display(row)))
            widget.set_class(index == self._cursor, "refresh-panel-row-selected")

    def _row_for_display(self, row: RefreshRow) -> RefreshRow:
        if row.choice != "usage" or self._usage_loaded:
            return row
        return replace(row, chip=_CHECKING_CHIP)

    def _row_for_choice(self, choice: RefreshChoice) -> RefreshRow | None:
        for row in self._rows:
            if row.choice == choice:
                return row
        return None

    @staticmethod
    def _row_classes(row: RefreshRow, *, selected: bool) -> str:
        classes = ["refresh-panel-row", "duration-choice-row"]
        if row.tone:
            classes.append(f"duration-choice-tone-{row.tone}")
        if selected:
            classes.append("refresh-panel-row-selected")
        return " ".join(classes)

    @staticmethod
    def _render_row(row: RefreshRow) -> str:
        chip = row.unavailable_reason if row.unavailable_reason else row.chip
        left_plain = f"  {row.key}  {row.title} · {row.target}"
        gap = max(1, _ROW_WIDTH - cell_len(left_plain) - cell_len(chip))
        padded = f"{' ' * gap}{escape(chip)}"
        if row.unavailable_reason:
            return (
                f"[dim]  {escape(row.key)}  {escape(row.title)} · "
                f"{escape(row.target)}{padded}\n      {escape(row.subtitle)}[/]"
            )
        return (
            f"  [bold]{escape(row.key)}[/]  [bold]{escape(row.title)}[/]"
            f"[dim] · {escape(row.target)}[/][dim]{padded}[/]\n"
            f"      [dim]{escape(row.subtitle)}[/]"
        )


def _cursor_index(rows: list[RefreshRow], choice: RefreshChoice) -> int:
    for index, row in enumerate(rows):
        if row.choice == choice:
            return index
    return 0


def _usage_target(status: UsageRowStatus, row: RefreshRow) -> str:
    count = status.provider_count
    if count <= 0:
        return row.target
    noun = "provider" if count == 1 else "providers"
    return f"{count} {noun}"


__all__ = [
    "RefreshChoice",
    "RefreshPanelModal",
    "RefreshRow",
    "UsageRowStatus",
]
