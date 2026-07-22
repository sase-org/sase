"""Reusable Textual controller for scope-aware config transactions."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from textual.containers import VerticalScroll
from textual.worker import Worker, WorkerState

from .config_transaction_preview import (
    ConfigTransactionPreview,
    coerce_transaction_preview,
)


@dataclass(frozen=True)
class ConfigTransactionMetadata:
    """Immutable identity/display metadata for one modal transaction."""

    title: str
    identity: tuple[str, ...] = ()
    running: bool = False
    generated_warning: str | None = None


@dataclass(frozen=True)
class ConfigTransactionRequest[MutationT]:
    """One immutable plan request tied to a controller generation."""

    transaction_id: int
    target: str
    mutation: MutationT
    metadata: ConfigTransactionMetadata


@dataclass(frozen=True)
class ConfigTransactionApplyResult[ResultT]:
    """Successful apply value plus an optional non-transactional warning."""

    value: ResultT
    note: str | None = None


@dataclass(frozen=True)
class ConfigTransactionScopeUpdate:
    """New host scope state plus the target selected after creation."""

    state: Any
    target: str


class ConfigTransactionInputError(ValueError):
    """Raised by a mutation builder when the current draft is invalid."""


class ConfigTransactionConflict(RuntimeError):
    """A typed stale-write conflict which must be reloaded/re-planned."""


def _is_config_transaction_conflict(error: BaseException | None) -> bool:
    """Recognize the shared type and compatible backend conflict types."""
    if isinstance(error, ConfigTransactionConflict):
        return True
    if error is None:
        return False
    class_name = type(error).__name__.lower()
    if "conflict" in class_name or bool(getattr(error, "is_conflict", False)):
        return True
    message = str(error).lower()
    return "stale write" in message or "changed since" in message


class ConfigTransactionControllerMixin:
    """Own scope, preview/apply workers, and conflict-safe lifecycle state.

    Host screens provide draft mutation building and small render/focus hooks.
    Every callback that may do planning, YAML, file, chezmoi, or git work runs
    in a thread worker.  Worker results are accepted only for the currently
    mounted transaction generation.
    """

    _stage: str
    _target: str | None
    _busy: bool
    _error: str | None
    _status: str | None
    _plan: Any

    def _init_config_transaction(
        self,
        *,
        metadata: ConfigTransactionMetadata,
        plan_callback: Callable[[ConfigTransactionRequest[Any]], Any],
        apply_callback: Callable[[Any], ConfigTransactionApplyResult[Any] | Any],
        preview_callback: Callable[[Any], ConfigTransactionPreview] | None = None,
        reload_callback: Callable[[], Any] | None = None,
        new_scope_modal_factory: Callable[[], Any] | None = None,
        create_scope_callback: Callable[[str], ConfigTransactionScopeUpdate]
        | None = None,
    ) -> None:
        self._transaction_metadata = metadata
        self._transaction_plan_callback = plan_callback
        self._transaction_apply_callback = apply_callback
        self._transaction_preview_callback = (
            preview_callback or coerce_transaction_preview
        )
        self._transaction_reload_callback = reload_callback
        self._transaction_new_scope_modal_factory = new_scope_modal_factory
        self._transaction_create_scope_callback = create_scope_callback
        self._transaction_id = 0
        self._transaction_conflict = False
        self._plan_worker: Worker[Any] | None = None
        self._apply_worker: Worker[Any] | None = None
        self._reload_worker: Worker[Any] | None = None
        self._scope_worker: Worker[Any] | None = None
        self._plan_worker_id: int | None = None
        self._apply_worker_id: int | None = None
        self._reload_worker_id: int | None = None
        self._scope_worker_id: int | None = None

    # -- host contract -------------------------------------------------

    def _writable_sources(self) -> Sequence[Any]:
        raise NotImplementedError

    def _build_transaction_mutation(self, target: str) -> Any:
        raise NotImplementedError

    def _render_transaction_state(self) -> None:
        render = getattr(self, "_render_all", None)
        if callable(render):
            render()

    def _focus_transaction_draft(self) -> None:
        focus = getattr(self, "_focus_editor", None)
        if callable(focus):
            focus()

    def _accept_transaction_reload(self, _value: Any) -> None:
        """Allow a host to replace seed/inventory data after a reload."""

    def _accept_transaction_scope_state(self, _state: Any) -> None:
        """Allow a host to replace immutable inventory after scope creation."""

    def _transaction_scope_changed(self) -> None:
        """Allow a host to refresh target-layer contribution metadata."""

    def _dismiss_transaction_result(self, value: Any) -> None:
        self.dismiss(value)  # type: ignore[attr-defined]

    # -- scope ---------------------------------------------------------

    def action_cycle_scope(self) -> None:
        if self._stage != "edit" or self._busy:
            return
        writable = self._writable_sources()
        if len(writable) <= 1:
            return
        names = [scope.name for scope in writable]
        index = names.index(self._target) if self._target in names else -1
        self._target = names[(index + 1) % len(names)]
        self._error = None
        self._transaction_conflict = False
        self._transaction_scope_changed()
        self._render_transaction_state()

    def _select_scope_index(self, index: int) -> None:
        if self._stage != "edit" or self._busy:
            return
        writable = self._writable_sources()
        if index < 0 or index >= len(writable):
            return
        self._target = writable[index].name
        self._error = None
        self._transaction_conflict = False
        self._transaction_scope_changed()
        self._render_transaction_state()

    def action_new_overlay(self) -> None:
        """Create a named writable scope through injected pure callbacks."""
        if self._stage != "edit" or self._busy:
            return
        factory = self._transaction_new_scope_modal_factory
        create = self._transaction_create_scope_callback
        if factory is None or create is None:
            return

        def named(name: str | None) -> None:
            if not name or not getattr(self, "is_mounted", False):
                return
            self._busy = True
            self._error = None
            self._status = "Creating overlay…"
            self._transaction_id += 1
            transaction_id = self._transaction_id
            self._render_transaction_state()

            def task() -> ConfigTransactionScopeUpdate:
                return create(name)

            self._scope_worker_id = transaction_id
            self._scope_worker = self.run_worker(  # type: ignore[attr-defined]
                task, thread=True, exclusive=True, exit_on_error=False
            )

        self.app.push_screen(factory(), named)  # type: ignore[attr-defined]

    # -- navigation ----------------------------------------------------

    def action_back(self) -> None:
        if self._busy:
            return
        if self._stage == "preview":
            self._stage = "edit"
            self._plan = None
            self._error = None
            self._status = None
            self._transaction_conflict = False
            self._render_transaction_state()
            self._focus_transaction_draft()
            return
        self.dismiss(None)  # type: ignore[attr-defined]

    def action_confirm(self) -> None:
        if self._busy:
            return
        if self._stage == "edit":
            self._start_plan()
        else:
            self._start_apply()

    def action_preview_page_down(self) -> None:
        self._scroll_preview(page_delta=1)

    def action_preview_page_up(self) -> None:
        self._scroll_preview(page_delta=-1)

    def action_preview_top(self) -> None:
        self._preview_scroll_widget().scroll_home(
            animate=False, immediate=True, force=True
        )

    def action_preview_bottom(self) -> None:
        self._preview_scroll_widget().scroll_end(
            animate=False, immediate=True, force=True
        )

    def _scroll_preview(self, *, lines: int = 0, page_delta: int = 0) -> None:
        if self._stage != "preview":
            return
        try:
            scroll = self._preview_scroll_widget()
        except Exception:
            return
        delta = lines
        if page_delta:
            height = scroll.scrollable_content_region.height
            delta += page_delta * max(1, height // 2)
        scroll.scroll_relative(y=delta, animate=False, immediate=True, force=True)

    def _preview_scroll_widget(self) -> VerticalScroll:
        return self.query_one(  # type: ignore[attr-defined]
            "#config-edit-preview-scroll", VerticalScroll
        )

    # -- plan/apply/reload workers ------------------------------------

    def _start_plan(self) -> None:
        target = self._target
        if target is None:
            self._error = "no writable target — create an overlay (ctrl+n)"
            self._render_transaction_state()
            return
        try:
            mutation = self._build_transaction_mutation(target)
        except ConfigTransactionInputError as exc:
            self._error = str(exc)
            self._render_transaction_state()
            return
        self._transaction_id += 1
        transaction_id = self._transaction_id
        request = ConfigTransactionRequest(
            transaction_id=transaction_id,
            target=target,
            mutation=mutation,
            metadata=self._transaction_metadata,
        )
        self._error = None
        self._status = None
        self._busy = True
        self._stage = "preview"
        self._plan = None
        self._transaction_conflict = False
        self.set_focus(None)  # type: ignore[attr-defined]
        self._render_transaction_state()

        def task() -> Any:
            return self._transaction_plan_callback(request)

        self._plan_worker_id = transaction_id
        self._plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, exit_on_error=False
        )

    def _start_apply(self) -> None:
        plan = self._plan
        if plan is None:
            return
        try:
            preview = self._transaction_preview_callback(plan)
        except Exception as exc:
            self._error = str(exc)
            self._render_transaction_state()
            return
        if not preview.is_valid:
            self._error = "fix validation errors before writing"
            self._render_transaction_state()
            return
        if not preview.text_diff.strip():
            self._error = "nothing to write — no change"
            self._render_transaction_state()
            return
        self._busy = True
        self._error = None
        self._render_transaction_state()
        transaction_id = self._transaction_id

        def task() -> Any:
            outcome = self._transaction_apply_callback(plan)
            if isinstance(outcome, ConfigTransactionApplyResult):
                return outcome
            return ConfigTransactionApplyResult(outcome)

        self._apply_worker_id = transaction_id
        self._apply_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, exit_on_error=False
        )

    def action_reload_transaction(self) -> None:
        """Reload external state after a conflict while preserving the draft."""
        if self._busy or not self._transaction_conflict:
            return
        callback = self._transaction_reload_callback
        if callback is None:
            self._error = None
            self._status = "review the preserved draft, then preview again"
            self._transaction_conflict = False
            self._render_transaction_state()
            self._focus_transaction_draft()
            return
        self._busy = True
        self._error = None
        self._status = "Reloading configuration…"
        self._transaction_id += 1
        transaction_id = self._transaction_id
        self._render_transaction_state()
        self._reload_worker_id = transaction_id
        self._reload_worker = self.run_worker(  # type: ignore[attr-defined]
            callback, thread=True, exclusive=True, exit_on_error=False
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._plan_worker:
            self._on_plan_worker(event)
        elif event.worker is self._apply_worker:
            self._on_apply_worker(event)
        elif event.worker is self._reload_worker:
            self._on_reload_worker(event)
        elif event.worker is self._scope_worker:
            self._on_scope_worker(event)

    def _on_plan_worker(self, event: Worker.StateChanged) -> None:
        if not self._worker_is_current(event.worker, self._plan_worker_id):
            return
        if event.state == WorkerState.SUCCESS:
            self._busy = False
            self._plan = event.worker.result
            self._render_transaction_state()
        elif event.state == WorkerState.ERROR:
            self._busy = False
            self._error = self._worker_error(event, "could not plan edit")
            self._stage = "edit"
            self._render_transaction_state()
            self._focus_transaction_draft()

    def _on_apply_worker(self, event: Worker.StateChanged) -> None:
        if not self._worker_is_current(event.worker, self._apply_worker_id):
            return
        if event.state == WorkerState.SUCCESS:
            self._busy = False
            outcome = event.worker.result
            if not isinstance(outcome, ConfigTransactionApplyResult):
                self._dismiss_transaction_result(outcome)
                return
            if outcome.note is not None:
                self._error = outcome.note
                self._render_transaction_state()
                return
            self._dismiss_transaction_result(outcome.value)
        elif event.state == WorkerState.ERROR:
            self._busy = False
            error = event.worker.error
            if _is_config_transaction_conflict(error):
                self._transaction_conflict = True
                self._stage = "edit"
                self._plan = None
                self._error = self._worker_error(
                    event, "configuration changed since preview"
                )
                self._status = "draft preserved · reload/re-plan before writing"
                self._render_transaction_state()
                self._focus_transaction_draft()
                return
            self._error = self._worker_error(event, "write failed")
            self._render_transaction_state()

    def _on_reload_worker(self, event: Worker.StateChanged) -> None:
        if not self._worker_is_current(event.worker, self._reload_worker_id):
            return
        if event.state == WorkerState.SUCCESS:
            self._busy = False
            self._accept_transaction_reload(event.worker.result)
            self._transaction_conflict = False
            self._status = "reloaded · review the preserved draft, then preview again"
            self._render_transaction_state()
            self._focus_transaction_draft()
        elif event.state == WorkerState.ERROR:
            self._busy = False
            self._error = self._worker_error(event, "reload failed")
            self._render_transaction_state()

    def _on_scope_worker(self, event: Worker.StateChanged) -> None:
        if not self._worker_is_current(event.worker, self._scope_worker_id):
            return
        if event.state == WorkerState.SUCCESS:
            self._busy = False
            update = event.worker.result
            if not isinstance(update, ConfigTransactionScopeUpdate):
                self._error = "could not create overlay: invalid scope result"
                self._render_transaction_state()
                return
            self._accept_transaction_scope_state(update.state)
            self._target = update.target
            self._status = None
            self._transaction_scope_changed()
            self._render_transaction_state()
            self._focus_transaction_draft()
        elif event.state == WorkerState.ERROR:
            self._busy = False
            self._error = self._worker_error(event, "could not create overlay")
            self._render_transaction_state()

    def _worker_is_current(
        self, worker: Worker[Any], transaction_id: int | None
    ) -> bool:
        return bool(
            getattr(self, "is_mounted", False)
            and transaction_id is not None
            and transaction_id == self._transaction_id
            and not worker.is_cancelled
        )

    @staticmethod
    def _worker_error(event: Worker.StateChanged, fallback: str) -> str:
        error = event.worker.error
        return str(error) if error else fallback

    def on_unmount(self) -> None:
        """Cancel all transaction workers and invalidate every late result."""
        self._transaction_id += 1
        for worker in (
            self._plan_worker,
            self._apply_worker,
            self._reload_worker,
            self._scope_worker,
        ):
            if worker is not None and not worker.is_finished:
                worker.cancel()
        self._plan_worker = None
        self._apply_worker = None
        self._reload_worker = None
        self._scope_worker = None


__all__ = [
    "ConfigTransactionApplyResult",
    "ConfigTransactionConflict",
    "ConfigTransactionControllerMixin",
    "ConfigTransactionInputError",
    "ConfigTransactionMetadata",
    "ConfigTransactionRequest",
    "ConfigTransactionScopeUpdate",
]

# Short aliases keep the shared contract pleasant for non-Config-Center users.
TransactionApplyResult = ConfigTransactionApplyResult
TransactionConflict = ConfigTransactionConflict
TransactionControllerMixin = ConfigTransactionControllerMixin
TransactionMetadata = ConfigTransactionMetadata
TransactionRequest = ConfigTransactionRequest
TransactionScopeUpdate = ConfigTransactionScopeUpdate
