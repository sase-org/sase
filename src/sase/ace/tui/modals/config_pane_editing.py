"""Editing and commit prompting for the Config Center config pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.config import AppliedResult

from .config_commit import (
    ConfigCommitOffer,
    push_config_commit_prompt,
    submit_config_commit_task,
)
from .config_pane_view import ConfigPaneView

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class ConfigPaneEditingMixin(_MixinBase):
    """Field editing and follow-up commit flow for ``ConfigPane``."""

    if TYPE_CHECKING:
        _config_commit_offer_worker: Worker[ConfigCommitOffer | None] | None
        _selected_path: str | None
        _view: ConfigPaneView | None

        def action_refresh(self) -> None: ...

    def action_edit_field(self) -> None:
        """Edit the selected leaf."""
        path = self._selected_path
        view = self._view
        if path is None or view is None:
            return
        field = view.fields_by_path.get(path)
        if field is None or not field.leaf:
            return
        self._open_editor(path)

    def _open_editor(self, path: str) -> None:
        view = self._view
        if view is None:
            return
        field = view.fields_by_path.get(path)
        if field is None or not field.leaf:
            return
        from sase.ace.tui.modals.config_edit_modal import ConfigEditModal

        self.app.push_screen(
            ConfigEditModal(view, field=field), self._on_edit_dismissed
        )

    def _on_edit_dismissed(self, result: Any) -> None:
        """After a successful write, refresh the inventory to show the change."""
        if not isinstance(result, AppliedResult):
            return
        self._notify_write_success(result)
        self.action_refresh()
        if tuple(result.key_path) == ("max_running_agents",):
            request_refresh = getattr(self.app, "request_agents_refresh", None)
            if callable(request_refresh):
                request_refresh("config")
        self._start_config_commit_offer(result)

    def _start_config_commit_offer(self, result: AppliedResult) -> None:
        """Discover a commit offer for the written path without blocking input."""
        self._cancel_config_commit_offer()
        target_path = result.path
        field_path = ".".join(result.key_path) or "configuration"
        verb = "Reset" if result.op == "unset" else "Update"
        subject = f"chore: {verb} config {field_path}"

        def task() -> ConfigCommitOffer | None:
            from . import config_pane as public_config_pane

            return public_config_pane._build_config_commit_offer(
                target_path,
                subject=subject,
            )

        self._config_commit_offer_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="config-pane-commit-offer",
        )

    def _on_config_commit_offer_worker_state(self, event: Worker.StateChanged) -> None:
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        self._config_commit_offer_worker = None
        if event.state != WorkerState.SUCCESS or not self.is_mounted:
            return
        offer = event.worker.result
        if offer is None:
            return
        push_config_commit_prompt(
            self.app,
            offer,
            message="Commit and push your config field change?",
            on_confirm=self._submit_commit_task,
        )

    def _cancel_config_commit_offer(self) -> None:
        worker = self._config_commit_offer_worker
        self._config_commit_offer_worker = None
        if worker is not None and not worker.is_finished:
            worker.cancel()

    def _submit_commit_task(self, offer: ConfigCommitOffer) -> None:
        submit_config_commit_task(
            self.app,
            offer,
            display_name=f"commit config {offer.rel_path}",
        )

    def _notify_write_success(self, result: AppliedResult) -> None:
        key_path = ".".join(result.key_path) if result.key_path else "(unknown)"
        target = result.path or "(unknown target)"
        message = f"wrote {key_path} → {target}"
        if result.used_chezmoi:
            message += " (chezmoi applied)"
        try:
            self.app.notify(message)
        except Exception:
            pass
