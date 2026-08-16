"""Modal for managing Models-panel provider routing."""

from __future__ import annotations
from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option
from textual.worker import Worker, WorkerState

from sase.llm_provider import (
    ProviderRoutingStatus,
    disable_provider,
    disable_provider_until,
    enable_provider,
)

from .base import OptionListNavigationMixin
from .duration_choice_modal import DurationChoiceCancelled
from .models_panel_duration import (
    OpenOverrideUntil,
    OverrideDurationResult,
    OverrideUntilCleared,
    RelativeOverrideDuration,
)
from .models_panel_provider_rendering import (
    _duration_suffix,
    _provider_description_text,
    _provider_duration_modal,
    _render_provider_row,
)
from .models_panel_provider_state import (
    _ProviderRoutingSnapshot,
    _ProviderWriteOutcome,
    _active_disable,
    _load_provider_routing_snapshot,
    _now,
    _provider_disable_route_key,
)
from .models_panel_time import (
    OverrideUntilBack,
    OverrideUntilModal,
    ResolvedOverrideUntil,
)

_SNAPSHOT_GROUP = "provider-routing-snapshot"
_WRITE_GROUP = "provider-routing-write"


class _ProviderRoutingModal(OptionListNavigationMixin, ModalScreen[bool]):
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
        ("x", "enable", "Enable"),
    ]

    def __init__(
        self,
        snapshot: _ProviderRoutingSnapshot,
        *,
        load_snapshot: Callable[[], _ProviderRoutingSnapshot] = (
            _load_provider_routing_snapshot
        ),
        on_snapshot: Callable[[_ProviderRoutingSnapshot, str | None], None]
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
        self._pending_duration: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | None
        ) = None
        self._snapshot_worker: Worker[_ProviderRoutingSnapshot] | None = None
        self._snapshot_keep_provider: str | None = None
        self._write_worker: Worker[_ProviderWriteOutcome] | None = None

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
                "[green]d/enter[/green]=Disable or change duration  "
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
        if self._write_busy():
            return
        status = self._selected_status()
        if status is None:
            return
        self._pending_provider = status.provider
        self.app.push_screen(
            _provider_duration_modal(status.provider),
            callback=self._on_provider_duration_picked,
        )

    def action_enable(self) -> None:
        if self._write_busy():
            return
        status = self._selected_status()
        if status is None:
            return
        if _active_disable(status.active_disable, now=self._now()) is None:
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
                    title=f"Disable {self._pending_provider.upper()} Until",
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
                _provider_duration_modal(provider),
                callback=self._on_provider_duration_picked,
            )
            return
        self._submit_disable(result)

    def _write_busy(self) -> bool:
        return self._write_worker is not None and not self._write_worker.is_finished

    def _now(self) -> float:
        return _now()

    def _start_snapshot_load(self, *, keep_provider: str | None = None) -> None:
        if self._snapshot_worker is not None and not self._snapshot_worker.is_finished:
            self._snapshot_worker.cancel()

        def task() -> _ProviderRoutingSnapshot:
            return self._load_snapshot()

        self._snapshot_keep_provider = keep_provider
        self._snapshot_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_SNAPSHOT_GROUP,
        )

    def _submit_disable(
        self,
        result: RelativeOverrideDuration | OverrideUntilCleared | ResolvedOverrideUntil,
    ) -> None:
        if self._write_busy() or not self._pending_provider:
            return
        if self._snapshot_worker is not None and not self._snapshot_worker.is_finished:
            self._snapshot_worker.cancel()
        provider = self._pending_provider
        before = _provider_disable_route_key(self._snapshot.provider_disables)

        def task() -> _ProviderWriteOutcome:
            try:
                if isinstance(result, ResolvedOverrideUntil):
                    disable_provider_until(
                        provider,
                        result.expires_at,
                        source="ace",
                        now=_now(),
                    )
                else:
                    seconds = (
                        result.seconds
                        if isinstance(result, RelativeOverrideDuration)
                        else None
                    )
                    disable_provider(provider, seconds, source="ace", now=_now())
                snapshot = self._load_snapshot()
                return _ProviderWriteOutcome(
                    action="disable",
                    provider=provider,
                    changed=before
                    != _provider_disable_route_key(snapshot.provider_disables),
                    snapshot=snapshot,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced in TUI toast.
                return _ProviderWriteOutcome(
                    action="disable",
                    provider=provider,
                    changed=False,
                    snapshot=None,
                    error=str(exc),
                )

        self._pending_duration = result
        self._write_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_WRITE_GROUP,
        )

    def _submit_enable(self, provider: str) -> None:
        if self._write_busy():
            return
        if self._snapshot_worker is not None and not self._snapshot_worker.is_finished:
            self._snapshot_worker.cancel()

        def task() -> _ProviderWriteOutcome:
            try:
                changed = enable_provider(provider)
                return _ProviderWriteOutcome(
                    action="enable",
                    provider=provider,
                    changed=changed,
                    snapshot=self._load_snapshot(),
                )
            except Exception as exc:  # noqa: BLE001 - surfaced in TUI toast.
                return _ProviderWriteOutcome(
                    action="enable",
                    provider=provider,
                    changed=False,
                    snapshot=None,
                    error=str(exc),
                )

        self._write_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_WRITE_GROUP,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._snapshot_worker:
            self._on_snapshot_worker(event)
        elif event.worker is self._write_worker:
            self._on_write_worker(event)

    def _on_snapshot_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        keep = self._snapshot_keep_provider
        self._snapshot_worker = None
        self._snapshot_keep_provider = None
        if event.state == WorkerState.SUCCESS and event.worker.result is not None:
            self._apply_snapshot(
                event.worker.result,
                keep_provider=keep,
                emit_snapshot=False,
            )
        elif event.state == WorkerState.ERROR:
            self.notify(
                f"Could not load provider routing: {event.worker.error}",
                severity="warning",
            )

    def _on_write_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        duration = self._pending_duration
        self._pending_duration = None
        self._write_worker = None
        if event.state == WorkerState.ERROR:
            self.notify(
                f"Could not update provider routing: {event.worker.error}",
                severity="error",
            )
            return
        outcome = event.worker.result
        if outcome is None:
            self.notify(
                "Could not update provider routing: unknown error", severity="error"
            )
            return
        if outcome.error is not None or outcome.snapshot is None:
            self.notify(
                f"Could not update provider routing: {outcome.error or 'unknown error'}",
                severity="error",
            )
            return
        self._apply_snapshot(
            outcome.snapshot,
            keep_provider=outcome.provider,
            emit_snapshot=outcome.changed,
        )
        if outcome.action == "disable":
            if outcome.changed:
                suffix = _duration_suffix(duration)
                self.notify(
                    f"{outcome.provider.upper()} disabled {suffix}; "
                    "alias routing refreshed."
                )
                self._changed = True
            else:
                self.notify(
                    f"{outcome.provider.upper()} already has that provider disable.",
                    severity="warning",
                )
        elif outcome.changed:
            self.notify(f"{outcome.provider.upper()} enabled for new launches.")
            self._changed = True
        else:
            self.notify(
                f"{outcome.provider.upper()} is already enabled.",
                severity="warning",
            )

    def _apply_snapshot(
        self,
        snapshot: _ProviderRoutingSnapshot,
        *,
        keep_provider: str | None,
        emit_snapshot: bool,
    ) -> None:
        self._snapshot = snapshot
        option_list = self.query_one("#provider-routing-list", OptionList)
        option_list.clear_options()
        option_list.add_options(self._build_options())
        self._restore_highlight(option_list, keep_provider)
        self._update_description()
        if emit_snapshot and self._on_snapshot is not None:
            self._on_snapshot(snapshot, self._highlighted_provider())

    def _build_options(self) -> list[Option]:
        statuses = self._snapshot.visible_statuses
        self._statuses_by_provider = {status.provider: status for status in statuses}
        if not statuses:
            return [
                Option(
                    Text("No user-facing LLM providers are registered.", style="dim"),
                    id="__empty__",
                    disabled=True,
                )
            ]
        now = self._now()
        return [
            Option(
                _render_provider_row(
                    status,
                    colors=self._snapshot.provider_colors,
                    now=now,
                ),
                id=status.provider,
            )
            for status in statuses
        ]

    @staticmethod
    def _option_is_disabled(option_list: OptionList, index: int) -> bool:
        try:
            return option_list.get_option_at_index(index).disabled
        except Exception:
            return True

    @classmethod
    def _first_enabled_option_index(cls, option_list: OptionList) -> int | None:
        for index in range(option_list.option_count):
            if not cls._option_is_disabled(option_list, index):
                return index
        return None

    def _set_highlighted_index(
        self,
        option_list: OptionList,
        index: int | None,
    ) -> None:
        self._updating_highlight = True
        try:
            option_list.highlighted = index
        finally:
            self._updating_highlight = False

    def _restore_highlight(
        self,
        option_list: OptionList,
        preferred: str | None,
    ) -> None:
        if preferred is not None:
            try:
                index = option_list.get_option_index(preferred)
                if not self._option_is_disabled(option_list, index):
                    self._set_highlighted_index(option_list, index)
                    return
            except Exception:
                pass
        self._set_highlighted_index(
            option_list,
            self._first_enabled_option_index(option_list),
        )

    def _highlighted_provider(self) -> str | None:
        option_list = self.query_one("#provider-routing-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        provider = str(option.id) if option.id is not None else ""
        return provider if provider in self._statuses_by_provider else None

    def _selected_status(self) -> ProviderRoutingStatus | None:
        provider = self._highlighted_provider()
        if provider is None:
            return None
        return self._statuses_by_provider.get(provider)

    def _update_description(self) -> None:
        try:
            description = self.query_one("#provider-routing-description", Static)
        except Exception:
            return
        description.update(
            _provider_description_text(self._selected_status(), now=self._now())
        )

    def on_option_list_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        if self._updating_highlight:
            return
        self._update_description()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_disable_or_change()
