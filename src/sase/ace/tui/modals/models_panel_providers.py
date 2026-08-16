"""Integrate provider-routing state into the Models panel."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.worker import Worker, WorkerState

from sase.bead.config import DEFAULT_BIG_EPIC_PHASE_THRESHOLD
from sase.llm_provider import (
    AliasView,
    ProviderRoutingStatus,
    TemporaryProviderDisable,
)

from .models_panel_provider_modal import ProviderRoutingModal
from .models_panel_provider_rendering import provider_title_line
from .models_panel_provider_state import (
    ProviderRoutingSnapshot,
    load_provider_routing_snapshot,
    provider_disable_route_key,
)
from .models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    LaunchModelSettingRow,
    build_launch_model_setting_rows,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class ModelsPanelProvidersMixin(_MixinBase):
    """Integrate provider-routing state into the Models panel."""

    if TYPE_CHECKING:
        _changed: bool
        _provider_disables: dict[str, TemporaryProviderDisable]
        _provider_routing_changed: bool
        _provider_snapshot: ProviderRoutingSnapshot
        _provider_snapshot_worker: Worker[ProviderRoutingSnapshot] | None
        _provider_snapshot_keep: str | None
        _provider_snapshot_signal_changes: bool
        _provider_snapshot_update_rows: bool
        _provider_statuses: tuple[ProviderRoutingStatus, ...]
        _launch_model_rows: tuple[
            LaunchModelSettingRow | BigEpicPhaseThresholdSettingRow, ...
        ]
        _views: list[AliasView]

        def _models_panel_now(self) -> float: ...

        def _load_models_panel_rows(self, views: list[AliasView]) -> list[Any]: ...

        def _replace_display(self, *, keep: str | None = None) -> None: ...

        def _highlighted_row_id(self) -> str | None: ...

        def _moved_highlight_row_id(self) -> str | None: ...

        def _update_context(self) -> None: ...

        def _emit_custom_builtin_shadow_warning(self) -> None: ...

    def _initial_provider_snapshot(self) -> ProviderRoutingSnapshot:
        launch_rows = build_launch_model_setting_rows(
            provider_disables={},
            big_epic_phase_threshold=DEFAULT_BIG_EPIC_PHASE_THRESHOLD,
        )
        return ProviderRoutingSnapshot(
            statuses=(),
            provider_disables={},
            alias_views=(),
            provider_colors={},
            captured_at=self._models_panel_now(),
            launch_model_rows=launch_rows,
            big_epic_phase_threshold=DEFAULT_BIG_EPIC_PHASE_THRESHOLD,
        )

    def _load_provider_routing_snapshot(self) -> ProviderRoutingSnapshot:
        return load_provider_routing_snapshot(self._models_panel_now())

    def _start_provider_snapshot_load(
        self,
        *,
        keep: str | None = None,
        update_rows: bool = False,
        signal_changes: bool = False,
    ) -> None:
        worker = self._provider_snapshot_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

        def task() -> ProviderRoutingSnapshot:
            return self._load_provider_routing_snapshot()

        self._provider_snapshot_keep = keep
        self._provider_snapshot_signal_changes = signal_changes
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
            self._start_provider_snapshot_load(update_rows=True, signal_changes=True)

    def _provider_title_text(self) -> Text | None:
        return provider_title_line(
            self._provider_disables, now=self._models_panel_now()
        )

    def _apply_provider_snapshot(
        self,
        snapshot: ProviderRoutingSnapshot,
        *,
        keep: str | None = None,
        update_rows: bool = True,
        signal_changes: bool = False,
    ) -> None:
        routing_changed = provider_disable_route_key(
            self._provider_disables
        ) != provider_disable_route_key(snapshot.provider_disables)
        self._provider_snapshot = snapshot
        self._provider_disables = dict(snapshot.provider_disables)
        self._provider_statuses = snapshot.visible_statuses
        if update_rows:
            self._launch_model_rows = snapshot.launch_model_rows
            self._views = list(snapshot.alias_views)
            self._top_rows = self._load_models_panel_rows(self._views)  # type: ignore[attr-defined]
        if self.is_mounted and update_rows:  # type: ignore[attr-defined]
            # Implicit snapshot completions omit keep. Preserve a user-moved
            # cursor; leave keep unset when the first-paint default is still
            # selected so launch-setting rows can become the new first row.
            preferred = keep if keep is not None else self._moved_highlight_row_id()
            self._replace_display(keep=preferred)
            self._emit_custom_builtin_shadow_warning()
        elif self.is_mounted:  # type: ignore[attr-defined]
            self._update_context()
        if signal_changes and routing_changed:
            self._changed = True
            self._provider_routing_changed = True

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
        signal_changes = self._provider_snapshot_signal_changes
        self._provider_snapshot_worker = None
        self._provider_snapshot_keep = None
        self._provider_snapshot_update_rows = False
        self._provider_snapshot_signal_changes = False
        if event.state == WorkerState.SUCCESS and event.worker.result is not None:
            self._apply_provider_snapshot(
                event.worker.result,
                keep=keep,
                update_rows=update_rows,
                signal_changes=signal_changes,
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
            ProviderRoutingModal(
                self._provider_snapshot,
                load_snapshot=self._load_provider_routing_snapshot,
                on_snapshot=self._on_provider_modal_snapshot,
            ),
            callback=self._on_provider_modal_dismissed,
        )

    def _on_provider_modal_snapshot(
        self,
        snapshot: ProviderRoutingSnapshot,
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


__all__ = ["ModelsPanelProvidersMixin"]
