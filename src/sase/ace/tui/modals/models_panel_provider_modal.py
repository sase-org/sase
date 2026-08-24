"""Modal for managing Models-panel provider routing."""

from __future__ import annotations
from collections.abc import Callable

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.worker import Worker

from sase.llm_provider import ProviderRoutingStatus
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
)

from .base import OptionListNavigationMixin
from .duration_choice_modal import DurationChoiceCancelled
from .models_panel_duration import (
    KeepCurrentWindow,
    OpenOverrideUntil,
    OverrideDurationResult,
    OverrideUntilCleared,
    RelativeOverrideDuration,
    now,
)
from .models_panel_provider_modal_drain import ProviderRoutingDrainMixin
from .models_panel_provider_modal_options import ProviderRoutingOptionsMixin
from .models_panel_provider_modal_workers import ProviderRoutingWorkersMixin
from .models_panel_provider_rendering import provider_duration_modal
from .models_panel_provider_state import (
    ProviderRoutingSnapshot,
    ProviderWriteOutcome,
    active_disable,
    load_provider_routing_snapshot,
)
from .models_panel_time import (
    OverrideUntilBack,
    OverrideUntilModal,
    ResolvedOverrideUntil,
)


class ProviderRoutingModal(
    OptionListNavigationMixin,
    ProviderRoutingOptionsMixin,
    ProviderRoutingWorkersMixin,
    ProviderRoutingDrainMixin,
    ModalScreen[bool],
):
    """Manage temporary provider routing state."""

    _option_list_id = "provider-routing-list"

    BINDINGS = [
        ("escape", "back", "Back"),
        ("q", "back", "Back"),
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("ctrl+n", "next_option", "Next"),
        ("ctrl+p", "prev_option", "Previous"),
        ("d", "disable_or_change", "Disable"),
        ("enter", "disable_or_change", "Disable"),
        ("s", "soft_disable", "Soft disable"),
        ("x", "enable", "Enable"),
    ]

    def __init__(
        self,
        snapshot: ProviderRoutingSnapshot,
        *,
        load_snapshot: Callable[[], ProviderRoutingSnapshot] = (
            load_provider_routing_snapshot
        ),
        on_snapshot: Callable[[ProviderRoutingSnapshot, str | None], None]
        | None = None,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._load_snapshot = load_snapshot
        self._on_snapshot = on_snapshot
        self._statuses_by_provider: dict[str, ProviderRoutingStatus] = {}
        self._updating_highlight = False
        self._changed = False
        self._pending_provider = ""
        self._pending_mode = PROVIDER_DISABLE_MODE_HARD
        self._pending_keep_current: KeepCurrentWindow | None = None
        self._pending_duration: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | KeepCurrentWindow
            | None
        ) = None
        self._snapshot_worker: Worker[ProviderRoutingSnapshot] | None = None
        self._snapshot_keep_provider: str | None = None
        self._write_worker: Worker[ProviderWriteOutcome] | None = None

    def compose(self) -> ComposeResult:
        with Container(id="provider-routing-container"):
            yield Static("Provider Routing", id="provider-routing-title")
            yield Static(
                "Applies to new launches, follow-ups, and fallback resolution.",
                id="provider-routing-summary",
            )
            yield OptionList(
                *self._build_options(),
                id="provider-routing-list",
            )
            yield Static("", id="provider-routing-description")
            yield Static(
                "[green]d/enter[/green]=Disable  "
                "[yellow]s[/yellow]=Soft disable "
                "[green]x[/green]=Enable  "
                "[dim]j/k[/dim]=Navigate  [dim]esc[/dim]=Back",
                id="provider-routing-footer",
            )

    def on_mount(self) -> None:
        option_list = self.query_one("#provider-routing-list", OptionList)
        option_list.focus()
        self._restore_highlight(option_list, None)
        self._update_description()
        self._start_snapshot_load()

    def on_unmount(self) -> None:
        for worker in (self._snapshot_worker, self._write_worker):
            if worker is not None and not worker.is_finished:
                worker.cancel()

    def action_back(self) -> None:
        if self._write_worker is not None and not self._write_worker.is_finished:
            self.notify(
                "A provider-routing update is still in progress.", severity="warning"
            )
            return
        self.dismiss(self._changed)

    def action_disable_or_change(self) -> None:
        self._begin_disable(PROVIDER_DISABLE_MODE_HARD)

    def action_soft_disable(self) -> None:
        self._begin_disable(PROVIDER_DISABLE_MODE_SOFT)

    def _begin_disable(self, mode: str) -> None:
        if self._write_busy():
            return
        status = self._selected_status()
        if status is None:
            return
        self._pending_provider = status.provider
        self._pending_mode = mode
        disable = active_disable(status.active_disable, now=self._now())
        keep_current = None
        if disable is not None and disable.mode != mode:
            keep_current = KeepCurrentWindow(expires_at=disable.expires_at)
        self._pending_keep_current = keep_current
        self.app.push_screen(
            provider_duration_modal(
                status.provider,
                mode=mode,
                keep_current=keep_current,
            ),
            callback=self._on_provider_duration_picked,
        )

    def _until_modal_title(self) -> str:
        verb = (
            "Soft-disable"
            if self._pending_mode == PROVIDER_DISABLE_MODE_SOFT
            else "Disable"
        )
        return f"{verb} {self._pending_provider.upper()} Until"

    def action_enable(self) -> None:
        if self._write_busy():
            return
        status = self._selected_status()
        if status is None:
            return
        if active_disable(status.active_disable, now=self._now()) is None:
            self.notify(
                f"{status.provider.upper()} is already enabled.",
                severity="warning",
            )
            return
        self._submit_enable(status.provider)

    def _on_provider_duration_picked(
        self,
        result: OverrideDurationResult | DurationChoiceCancelled | None,
    ) -> None:
        if result is None or isinstance(result, DurationChoiceCancelled):
            return
        if isinstance(result, OpenOverrideUntil):
            self.app.push_screen(
                OverrideUntilModal(
                    title=self._until_modal_title(),
                    submit_label="Set disable",
                ),
                callback=self._on_provider_until_picked,
            )
            return
        self._submit_disable(result)

    def _on_provider_until_picked(
        self,
        result: ResolvedOverrideUntil | OverrideUntilBack | None,
    ) -> None:
        if result is None:
            return
        if isinstance(result, OverrideUntilBack):
            provider = self._pending_provider
            self.app.push_screen(
                provider_duration_modal(
                    provider,
                    mode=self._pending_mode,
                    keep_current=self._pending_keep_current,
                ),
                callback=self._on_provider_duration_picked,
            )
            return
        self._submit_disable(result)

    def _now(self) -> float:
        return now()
