"""Snapshot/write worker orchestration for `ProviderRoutingModal`."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from textual.widgets import OptionList
from textual.worker import Worker, WorkerState

from sase.agent.provider_drain import ProviderDrainError, plan_provider_drain
from sase.llm_provider import disable_provider, disable_provider_until, enable_provider
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
)

from .models_panel_duration import (
    KeepCurrentWindow,
    OverrideUntilCleared,
    RelativeOverrideDuration,
)
from .models_panel_provider_rendering import duration_suffix
from .models_panel_provider_state import (
    ProviderRoutingSnapshot,
    ProviderWriteOutcome,
    active_disable,
    provider_disable_route_key,
)
from .models_panel_time import ResolvedOverrideUntil

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object

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


class ProviderRoutingWorkersMixin(_MixinBase):
    """Load routing snapshots and submit provider disable/enable writes."""

    if TYPE_CHECKING:
        _snapshot: ProviderRoutingSnapshot
        _load_snapshot: Callable[[], ProviderRoutingSnapshot]
        _on_snapshot: Callable[[ProviderRoutingSnapshot, str | None], None] | None
        _changed: bool
        _pending_duration: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | KeepCurrentWindow
            | None
        )
        _snapshot_worker: Worker[ProviderRoutingSnapshot] | None
        _snapshot_keep_provider: str | None
        _write_worker: Worker[ProviderWriteOutcome] | None
        _pending_provider: str
        _pending_mode: str

        def _now(self) -> float: ...

        def _build_options(self) -> list[Any]: ...

        def _restore_highlight(
            self, option_list: OptionList, preferred: str | None
        ) -> None: ...

        def _update_description(self) -> None: ...

        def _highlighted_provider(self) -> str | None: ...

        def _maybe_prompt_provider_drain(
            self, outcome: ProviderWriteOutcome
        ) -> None: ...

    def _write_busy(self) -> bool:
        return self._write_worker is not None and not self._write_worker.is_finished

    def _start_snapshot_load(self, *, keep_provider: str | None = None) -> None:
        if self._snapshot_worker is not None and not self._snapshot_worker.is_finished:
            self._snapshot_worker.cancel()

        def task() -> ProviderRoutingSnapshot:
            return self._load_snapshot()

        self._snapshot_keep_provider = keep_provider
        self._snapshot_worker = self.run_worker(  # type: ignore[attr-defined]
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
                captured_now = self._now()
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
        self._write_worker = self.run_worker(  # type: ignore[attr-defined]
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

        self._write_worker = self.run_worker(  # type: ignore[attr-defined]
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
            self.notify(  # type: ignore[attr-defined]
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
            self.notify(  # type: ignore[attr-defined]
                f"Could not update provider routing: {event.worker.error}",
                severity="error",
            )
            return
        outcome = event.worker.result
        if outcome is None:
            self.notify(  # type: ignore[attr-defined]
                "Could not update provider routing: unknown error", severity="error"
            )
            return
        if outcome.error is not None or outcome.snapshot is None:
            self.notify(  # type: ignore[attr-defined]
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
                self.notify(_disable_success_toast(outcome, duration))  # type: ignore[attr-defined]
                self._changed = True
                self._maybe_prompt_provider_drain(outcome)
            else:
                self.notify(  # type: ignore[attr-defined]
                    f"{outcome.provider.upper()} already has that provider disable.",
                    severity="warning",
                )
        elif outcome.changed:
            self.notify(f"{outcome.provider.upper()} enabled for new launches.")  # type: ignore[attr-defined]
            self._changed = True
        else:
            self.notify(  # type: ignore[attr-defined]
                f"{outcome.provider.upper()} is already enabled.",
                severity="warning",
            )

    def _apply_snapshot(
        self,
        snapshot: ProviderRoutingSnapshot,
        *,
        keep_provider: str | None,
        emit_snapshot: bool,
    ) -> None:
        self._snapshot = snapshot
        option_list = self.query_one("#provider-routing-list", OptionList)  # type: ignore[attr-defined]
        option_list.clear_options()
        option_list.add_options(self._build_options())
        self._restore_highlight(option_list, keep_provider)
        self._update_description()
        if emit_snapshot and self._on_snapshot is not None:
            self._on_snapshot(snapshot, self._highlighted_provider())
