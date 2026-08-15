"""Provider-routing manager for the Models panel."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import math
from typing import TYPE_CHECKING, Any, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option
from textual.worker import Worker, WorkerState

from sase.core.time import get_timezone
from sase.llm_provider import (
    AliasView,
    ProviderRoutingStatus,
    TemporaryProviderDisable,
    build_alias_views,
    build_provider_routing_statuses,
    disable_provider,
    disable_provider_until,
    enable_provider,
    get_active_provider_disables,
)
from sase.llm_provider.registry import provider_cli_status_color_map

from .base import OptionListNavigationMixin
from .duration_choice_modal import DurationChoiceCancelled
from .models_panel_duration import (
    DurationPickerModal,
    OpenOverrideUntil,
    OverrideDurationResult,
    OverrideUntilCleared,
    RelativeOverrideDuration,
    format_duration_chosen,
    format_remaining,
)
from .models_panel_time import (
    OverrideUntilBack,
    OverrideUntilModal,
    ResolvedOverrideUntil,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object

_PROVIDER_CELL = 14
_COUNT_CELL = 10
_DISABLED_STYLE = "bold #FFAF5F"
_AVAILABLE_STYLE = "bold #87D787"
_CLI_MISSING_STYLE = "dim #A8A8A8"
_DESCRIPTION_STYLE = "#B0B0B0"
_SNAPSHOT_GROUP = "provider-routing-snapshot"
_WRITE_GROUP = "provider-routing-write"


@dataclass(frozen=True)
class _ProviderRoutingSnapshot:
    """One immutable provider-routing snapshot for UI rendering."""

    statuses: tuple[ProviderRoutingStatus, ...]
    provider_disables: Mapping[str, TemporaryProviderDisable]
    alias_views: tuple[AliasView, ...]
    provider_colors: Mapping[str, str]
    captured_at: float

    @property
    def visible_statuses(self) -> tuple[ProviderRoutingStatus, ...]:
        """Return human-facing providers, excluding hidden/test-only entries."""
        return tuple(
            status for status in self.statuses if not status.hidden_from_model_pickers
        )


@dataclass(frozen=True)
class _ProviderWriteOutcome:
    """Result returned by a provider-routing write worker."""

    action: Literal["disable", "enable"]
    provider: str
    changed: bool
    snapshot: _ProviderRoutingSnapshot | None
    error: str | None = None


def _load_provider_routing_snapshot(
    now: float | None = None,
) -> _ProviderRoutingSnapshot:
    """Load provider routing, disables, alias views, and colors together."""
    captured_at = (
        float(now) if now is not None and math.isfinite(now) and now > 0.0 else _now()
    )
    disables = get_active_provider_disables(captured_at)
    statuses = build_provider_routing_statuses(disables)
    views = tuple(build_alias_views(now=captured_at, provider_disables=disables))
    return _ProviderRoutingSnapshot(
        statuses=statuses,
        provider_disables=dict(disables),
        alias_views=views,
        provider_colors=provider_cli_status_color_map(),
        captured_at=captured_at,
    )


def _now() -> float:
    from .models_panel_duration import now

    return now()


def _pad(value: str, width: int) -> str:
    if len(value) > width:
        return value[: max(0, width - 1)] + "…"
    return value.ljust(width)


def _provider_label(provider: str, colors: Mapping[str, str]) -> Text:
    label = Text(no_wrap=True, overflow="ellipsis")
    color = colors.get(provider, "#87D7FF")
    label.append(_pad(provider.upper(), _PROVIDER_CELL), style=f"bold {color}")
    return label


def _remaining_label(
    disable: TemporaryProviderDisable,
    *,
    now: float,
    include_left: bool = True,
) -> str:
    if disable.expires_at is None:
        return "until cleared"
    suffix = " left" if include_left else ""
    return f"{format_remaining(disable.expires_at - now)}{suffix}"


def _active_disable(
    disable: TemporaryProviderDisable | None,
    *,
    now: float,
) -> TemporaryProviderDisable | None:
    if disable is None:
        return None
    if disable.expires_at is not None and now >= disable.expires_at:
        return None
    return disable


def _render_provider_row(
    status: ProviderRoutingStatus,
    *,
    colors: Mapping[str, str],
    now: float,
) -> Text:
    """Render one provider-routing row."""
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append_text(_provider_label(status.provider, colors))
    text.append(" ")
    count = f"{status.model_count} model"
    if status.model_count != 1:
        count += "s"
    text.append(_pad(count, _COUNT_CELL), style="dim")
    text.append("   ")
    disable = _active_disable(status.active_disable, now=now)
    if disable is not None:
        text.append(
            f"disabled · {_remaining_label(disable, now=now)}",
            style=_DISABLED_STYLE,
        )
    elif status.cli_available:
        text.append("available", style=_AVAILABLE_STYLE)
    else:
        text.append("CLI missing", style=_CLI_MISSING_STYLE)
    return text


def _provider_title_line(
    disables: Mapping[str, TemporaryProviderDisable],
    *,
    now: float,
) -> Text | None:
    """Return the conditional Models-title provider-disable summary."""
    entries: list[str] = []
    for provider, disable in sorted(disables.items()):
        if _active_disable(disable, now=now) is None:
            continue
        entries.append(
            f"{provider.upper()} {_remaining_label(disable, now=now, include_left=False)}"
        )
    if not entries:
        return None
    text = Text("disabled providers: ", style="dim")
    text.append(" · ".join(entries), style=_DISABLED_STYLE)
    return text


def _affected_aliases_text(status: ProviderRoutingStatus) -> str:
    aliases = tuple(f"@{name}" for name in status.affected_aliases)
    if not aliases:
        return "No configured aliases currently mention it."
    joined = ", ".join(aliases[:5])
    if len(aliases) > 5:
        joined = f"{joined}, +{len(aliases) - 5}"
    return f"Affected aliases: {joined}."


def _provider_description_text(
    status: ProviderRoutingStatus | None,
    *,
    now: float,
) -> Text:
    """Return the fixed-height provider description strip."""
    if status is None:
        return Text("", style=_DESCRIPTION_STYLE)
    text = Text(style=_DESCRIPTION_STYLE, no_wrap=False)
    label = status.provider.upper()
    disable = _active_disable(status.active_disable, now=now)
    if disable is not None:
        text.append(
            f"New launches and fallbacks route around {label}; "
            "running provider processes continue.",
            style=_DISABLED_STYLE,
        )
        if disable.expires_at is None:
            end = "until cleared"
        else:
            end = datetime.fromtimestamp(disable.expires_at, get_timezone()).strftime(
                "%b %-d %-I:%M%p"
            )
            end = f"until {end} ({_remaining_label(disable, now=now)})"
        text.append(f"\n{end}. {_affected_aliases_text(status)}", style="dim")
    elif not status.cli_available:
        text.append(
            f"{label} CLI is unavailable; automatic selector routing already skips it.",
            style=_CLI_MISSING_STYLE,
        )
        text.append(
            "\nA manual disable can still record temporary routing state for later.",
            style="dim",
        )
    else:
        text.append(
            f"{label} is available for new launches.",
            style=_AVAILABLE_STYLE,
        )
        text.append(
            "\nDisable it to route future launches and fallbacks around it; "
            "running processes continue.",
            style="dim",
        )
    return text


class _ProviderRoutingModal(
    OptionListNavigationMixin,
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
        ("x", "enable", "Enable"),
    ]

    def __init__(
        self,
        snapshot: _ProviderRoutingSnapshot,
        *,
        load_snapshot: Callable[
            [], _ProviderRoutingSnapshot
        ] = _load_provider_routing_snapshot,
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
                return _ProviderWriteOutcome(
                    action="disable",
                    provider=provider,
                    changed=True,
                    snapshot=self._load_snapshot(),
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
            self._apply_snapshot(event.worker.result, keep_provider=keep)
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
        self._apply_snapshot(outcome.snapshot, keep_provider=outcome.provider)
        if outcome.action == "disable":
            suffix = _duration_suffix(duration)
            self.notify(
                f"{outcome.provider.upper()} disabled {suffix}; alias routing refreshed."
            )
            self._changed = True
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
    ) -> None:
        self._snapshot = snapshot
        option_list = self.query_one("#provider-routing-list", OptionList)
        option_list.clear_options()
        option_list.add_options(self._build_options())
        self._restore_highlight(option_list, keep_provider)
        self._update_description()
        if self._on_snapshot is not None:
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


def _provider_duration_modal(provider: str) -> DurationPickerModal:
    label = provider.upper()
    return DurationPickerModal(
        title=f"Disable {label}",
        quick_subtitle=f"Route new launches around {label} briefly.",
        short_subtitle=f"Keep {label} out of routing through a short task.",
        hour_subtitle=f"Route new launches around {label} for a focused session.",
        two_hour_subtitle=f"Keep {label} disabled for a longer implementation block.",
        four_hour_subtitle=f"Keep {label} disabled for half a day.",
        until_cleared_subtitle=f"Keep {label} disabled until you enable it.",
        until_time_subtitle="Choose a local clock time or date.",
        custom_placeholder="e.g., 30m, 2h, 1h30m, until cleared",
        id_prefix="provider-duration",
    )


def _duration_suffix(
    result: (
        RelativeOverrideDuration | OverrideUntilCleared | ResolvedOverrideUntil | None
    ),
) -> str:
    if isinstance(result, ResolvedOverrideUntil):
        return f"until {result.notification_display}"
    if isinstance(result, OverrideUntilCleared):
        return "until cleared"
    if isinstance(result, RelativeOverrideDuration):
        return f"for {format_duration_chosen(result.seconds)}"
    return "temporarily"


class ModelsPanelProvidersMixin(_MixinBase):
    """Integrate provider-routing state into the Models panel."""

    if TYPE_CHECKING:
        _changed: bool
        _provider_disables: dict[str, TemporaryProviderDisable]
        _provider_routing_changed: bool
        _provider_snapshot: _ProviderRoutingSnapshot
        _provider_snapshot_worker: Worker[_ProviderRoutingSnapshot] | None
        _provider_snapshot_keep: str | None
        _provider_snapshot_update_rows: bool
        _provider_statuses: tuple[ProviderRoutingStatus, ...]
        _views: list[AliasView]

        def _models_panel_now(self) -> float: ...

        def _load_models_panel_rows(self, views: list[AliasView]) -> list[Any]: ...

        def _replace_display(self, *, keep: str | None = None) -> None: ...

        def _update_context(self) -> None: ...

    def _initial_provider_snapshot(self) -> _ProviderRoutingSnapshot:
        return _ProviderRoutingSnapshot(
            statuses=(),
            provider_disables={},
            alias_views=(),
            provider_colors={},
            captured_at=self._models_panel_now(),
        )

    def _load_provider_routing_snapshot(self) -> _ProviderRoutingSnapshot:
        return _load_provider_routing_snapshot(self._models_panel_now())

    def _start_provider_snapshot_load(
        self,
        *,
        keep: str | None = None,
        update_rows: bool = False,
    ) -> None:
        worker = self._provider_snapshot_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

        def task() -> _ProviderRoutingSnapshot:
            return self._load_provider_routing_snapshot()

        self._provider_snapshot_keep = keep
        self._provider_snapshot_update_rows = update_rows
        self._provider_snapshot_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="models-provider-routing-snapshot",
        )

    def _cancel_provider_workers(self) -> None:
        worker = self._provider_snapshot_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

    def _provider_write_busy(self) -> bool:
        return False

    def _refresh_provider_clock(self) -> None:
        """Refresh countdowns and reload once an expiry crosses."""
        self._update_context()
        now = self._models_panel_now()
        if not any(
            disable.expires_at is not None and now >= disable.expires_at
            for disable in self._provider_disables.values()
        ):
            return
        worker = self._provider_snapshot_worker
        if worker is None or worker.is_finished:
            self._start_provider_snapshot_load(update_rows=True)

    def _provider_title_text(self) -> Text | None:
        return _provider_title_line(
            self._provider_disables, now=self._models_panel_now()
        )

    def _apply_provider_snapshot(
        self,
        snapshot: _ProviderRoutingSnapshot,
        *,
        keep: str | None = None,
        update_rows: bool = True,
    ) -> None:
        self._provider_snapshot = snapshot
        self._provider_disables = dict(snapshot.provider_disables)
        self._provider_statuses = snapshot.visible_statuses
        if update_rows:
            self._views = list(snapshot.alias_views)
            self._top_rows = self._load_models_panel_rows(self._views)  # type: ignore[attr-defined]
        if self.is_mounted and update_rows:  # type: ignore[attr-defined]
            self._replace_display(keep=keep)
        elif self.is_mounted:  # type: ignore[attr-defined]
            self._update_context()

    def _on_provider_snapshot_worker_state(self, event: Worker.StateChanged) -> bool:
        if event.worker is not self._provider_snapshot_worker:
            return False
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return True
        keep = self._provider_snapshot_keep
        update_rows = self._provider_snapshot_update_rows
        self._provider_snapshot_worker = None
        self._provider_snapshot_keep = None
        self._provider_snapshot_update_rows = False
        if event.state == WorkerState.SUCCESS and event.worker.result is not None:
            self._apply_provider_snapshot(
                event.worker.result,
                keep=keep,
                update_rows=update_rows,
            )
        elif event.state == WorkerState.ERROR and self.is_mounted:  # type: ignore[attr-defined]
            self.notify(  # type: ignore[attr-defined]
                f"Could not load provider routing: {event.worker.error}",
                severity="warning",
            )
        return True

    def action_providers(self) -> None:
        """Open the provider-routing manager."""
        self.app.push_screen(  # type: ignore[attr-defined]
            _ProviderRoutingModal(
                self._provider_snapshot,
                load_snapshot=self._load_provider_routing_snapshot,
                on_snapshot=self._on_provider_modal_snapshot,
            ),
            callback=self._on_provider_modal_dismissed,
        )

    def _on_provider_modal_snapshot(
        self,
        snapshot: _ProviderRoutingSnapshot,
        _keep_provider: str | None,
    ) -> None:
        selected = self._highlighted_row_id()  # type: ignore[attr-defined]
        self._apply_provider_snapshot(snapshot, keep=selected, update_rows=True)
        self._changed = True
        self._provider_routing_changed = True

    def _on_provider_modal_dismissed(self, changed: bool | None) -> None:
        if changed:
            self._changed = True
            self._provider_routing_changed = True


__all__ = [
    "ModelsPanelProvidersMixin",
]
