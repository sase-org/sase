"""Modal for managing Models-panel provider routing."""

from __future__ import annotations
from collections.abc import Callable, Mapping
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.tui.actions.agent_durable import submit_provider_drain
from sase.agent.provider_drain import ProviderDrainError, plan_provider_drain
from sase.llm_provider import (
    ProviderRoutingStatus,
    disable_provider,
    disable_provider_until,
    enable_provider,
)
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
)

from .base import OptionListNavigationMixin
from .duration_choice_modal import DurationChoiceCancelled
from .model_picker_modal import ModelPickerModal
from .models_panel_duration import (
    KeepCurrentWindow,
    OpenOverrideUntil,
    OverrideDurationResult,
    OverrideUntilCleared,
    RelativeOverrideDuration,
    now,
)
from .models_panel_provider_rendering import (
    duration_suffix,
    provider_description_text,
    provider_duration_modal,
    render_provider_row,
)
from .models_panel_provider_state import (
    ProviderRoutingSnapshot,
    ProviderWriteOutcome,
    active_disable,
    load_provider_routing_snapshot,
    provider_disable_route_key,
)
from .models_panel_time import (
    OverrideUntilBack,
    OverrideUntilModal,
    ResolvedOverrideUntil,
)
from .provider_drain_prompt_modal import (
    ProviderDrainPromptDecision,
    ProviderDrainPromptModal,
)

_SNAPSHOT_GROUP = "provider-routing-snapshot"
_WRITE_GROUP = "provider-routing-write"
_PROVIDER_DRAIN_FLAG = "provider_drain"
_PROVIDER_DRAIN_PREVIEW_LIMIT = 20


def _disable_success_toast(
    outcome: ProviderWriteOutcome,
    duration: (
        RelativeOverrideDuration
        | OverrideUntilCleared
        | ResolvedOverrideUntil
        | KeepCurrentWindow
        | None
    ),
) -> str:
    """Return the success toast for a provider-disable write."""
    verb = "soft-disabled" if outcome.mode == PROVIDER_DISABLE_MODE_SOFT else "disabled"
    suffix = duration_suffix(duration)
    was = ""
    if outcome.previous_mode is not None and outcome.previous_mode != outcome.mode:
        was = (
            " (was soft)"
            if outcome.previous_mode == PROVIDER_DISABLE_MODE_SOFT
            else " (was disabled)"
        )
    return f"{outcome.provider.upper()} {verb} {suffix}{was}; alias routing refreshed."


def _provider_drain_flag_enabled() -> bool:
    """Return whether the provider-drain ACE prompt should be offered."""
    from sase.feature_flags.models import FeatureFlagError
    from sase.feature_flags.snapshot import current_flags

    try:
        return current_flags().enabled(_PROVIDER_DRAIN_FLAG)
    except FeatureFlagError:
        return False


def _provider_drain_preview(
    provider: str,
    *,
    mode: str,
    changed: bool,
    snapshot: ProviderRoutingSnapshot,
    captured_now: float,
) -> tuple[Any | None, str | None]:
    """Plan a drain preview for a changed manual hard-disable write."""
    if not changed or mode != PROVIDER_DISABLE_MODE_HARD:
        return None, None
    if not _provider_drain_flag_enabled():
        return None, None
    disable = active_disable(snapshot.provider_disables.get(provider), now=captured_now)
    if disable is None or not disable.is_hard:
        return None, None
    try:
        plan = plan_provider_drain(
            provider,
            limit=_PROVIDER_DRAIN_PREVIEW_LIMIT,
            now=captured_now,
        )
    except ProviderDrainError:
        return None, None
    except Exception as exc:  # noqa: BLE001 - preview must not fail the write.
        return None, str(exc)
    if not plan.moves and not plan.skips:
        return None, None
    return plan, None


def _completion_count_text(count: int, singular: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"


def _drain_completion_message(payload: Mapping[str, Any] | None) -> str:
    """Return a compact toast from the stable drain result envelope."""
    counts = payload.get("counts") if isinstance(payload, Mapping) else None
    if not isinstance(counts, Mapping):
        return "Provider drain completed."
    relaunched = _payload_count(counts, "relaunched")
    skipped = _payload_count(counts, "skipped")
    failed = _payload_count(counts, "failed")
    message = (
        f"Relaunched {_completion_count_text(relaunched, 'agent')}; "
        f"{skipped} left alone"
    )
    if failed:
        message = f"{message}; {failed} failed"
    return message


def _payload_count(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, int) and value >= 0:
        return value
    return 0


class ProviderRoutingModal(OptionListNavigationMixin, ModalScreen[bool]):
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

    def _write_busy(self) -> bool:
        return self._write_worker is not None and not self._write_worker.is_finished

    def _now(self) -> float:
        return now()

    def _start_snapshot_load(self, *, keep_provider: str | None = None) -> None:
        if self._snapshot_worker is not None and not self._snapshot_worker.is_finished:
            self._snapshot_worker.cancel()

        def task() -> ProviderRoutingSnapshot:
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
        result: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | KeepCurrentWindow
        ),
    ) -> None:
        if self._write_busy() or not self._pending_provider:
            return
        if self._snapshot_worker is not None and not self._snapshot_worker.is_finished:
            self._snapshot_worker.cancel()
        provider = self._pending_provider
        mode = self._pending_mode
        before = provider_disable_route_key(self._snapshot.provider_disables)
        previous = active_disable(
            self._snapshot.provider_disables.get(provider),
            now=self._now(),
        )
        previous_mode = previous.mode if previous is not None else None

        def task() -> ProviderWriteOutcome:
            try:
                captured_now = now()
                if isinstance(result, KeepCurrentWindow):
                    if result.expires_at is None:
                        disable_provider(
                            provider,
                            None,
                            source="ace",
                            mode=mode,
                            now=captured_now,
                        )
                    else:
                        disable_provider_until(
                            provider,
                            result.expires_at,
                            source="ace",
                            mode=mode,
                            now=captured_now,
                        )
                elif isinstance(result, ResolvedOverrideUntil):
                    disable_provider_until(
                        provider,
                        result.expires_at,
                        source="ace",
                        mode=mode,
                        now=captured_now,
                    )
                else:
                    seconds = (
                        result.seconds
                        if isinstance(result, RelativeOverrideDuration)
                        else None
                    )
                    disable_provider(
                        provider,
                        seconds,
                        source="ace",
                        mode=mode,
                        now=captured_now,
                    )
                snapshot = self._load_snapshot()
                changed = before != provider_disable_route_key(
                    snapshot.provider_disables
                )
                drain_preview, drain_preview_error = _provider_drain_preview(
                    provider,
                    mode=mode,
                    changed=changed,
                    snapshot=snapshot,
                    captured_now=captured_now,
                )
                return ProviderWriteOutcome(
                    action="disable",
                    provider=provider,
                    changed=changed,
                    snapshot=snapshot,
                    mode=mode,
                    previous_mode=previous_mode,
                    drain_preview=drain_preview,
                    drain_preview_error=drain_preview_error,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced in TUI toast.
                return ProviderWriteOutcome(
                    action="disable",
                    provider=provider,
                    changed=False,
                    snapshot=None,
                    error=str(exc),
                    mode=mode,
                    previous_mode=previous_mode,
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

        def task() -> ProviderWriteOutcome:
            try:
                changed = enable_provider(provider)
                return ProviderWriteOutcome(
                    action="enable",
                    provider=provider,
                    changed=changed,
                    snapshot=self._load_snapshot(),
                )
            except Exception as exc:  # noqa: BLE001 - surfaced in TUI toast.
                return ProviderWriteOutcome(
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
                self.notify(_disable_success_toast(outcome, duration))
                self._changed = True
                self._maybe_prompt_provider_drain(outcome)
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

    def _maybe_prompt_provider_drain(self, outcome: ProviderWriteOutcome) -> None:
        if outcome.drain_preview_error:
            self.notify(
                f"Provider drain preview unavailable: {outcome.drain_preview_error}",
                severity="warning",
            )
            return
        plan = outcome.drain_preview
        if plan is None:
            return
        self.app.push_screen(
            ProviderDrainPromptModal(plan, now=self._now()),
            callback=lambda decision: self._on_provider_drain_decision(plan, decision),
        )

    def _on_provider_drain_decision(
        self,
        plan: Any,
        decision: ProviderDrainPromptDecision | None,
    ) -> None:
        if decision is None or decision.action == "leave":
            return
        if decision.action == "pick_model":
            self.app.push_screen(
                ModelPickerModal(
                    title=f"Relaunch {plan.provider.upper()} Agents On",
                    include_default_option=False,
                    provider_disables=self._snapshot.provider_disables,
                ),
                callback=lambda model: self._on_provider_drain_model(plan, model),
            )
            return
        self._submit_provider_drain(plan.provider)

    def _on_provider_drain_model(self, plan: Any, model: str | None) -> None:
        if model is None:
            return
        self._submit_provider_drain(plan.provider, model=model)

    def _submit_provider_drain(
        self, provider: str, *, model: str | None = None
    ) -> None:
        app = self.app

        def on_complete(completion: Any) -> None:
            if completion.collision:
                app.notify(
                    f"A provider drain is already running for {provider.upper()}.",
                    severity="warning",
                )
                return
            if not completion.success:
                app.notify(
                    (
                        "Provider drain proc "
                        f"{completion.proc_info.proc_id} failed; inspect Procs: "
                        f"{completion.message}"
                    ),
                    severity="error",
                )
                return
            app.notify(_drain_completion_message(completion.payload))

        try:
            submitted = submit_provider_drain(
                app,
                provider=provider,
                model=model,
                on_complete=on_complete,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced in TUI toast.
            self.notify(f"Could not submit provider drain: {exc}", severity="error")
            return
        if submitted:
            suffix = f" on {model}" if model else ""
            self.notify(f"Drain submitted for {provider.upper()}{suffix}; watch Procs.")

    def _apply_snapshot(
        self,
        snapshot: ProviderRoutingSnapshot,
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
                render_provider_row(
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
            provider_description_text(self._selected_status(), now=self._now())
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
