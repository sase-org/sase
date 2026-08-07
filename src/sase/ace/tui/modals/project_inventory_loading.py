"""Worker-backed load lifecycle shared by the two inventory panes.

Both inventory sub-tabs scan the filesystem off the UI thread and repaint from
the cached result, so the reload cycle -- worker launch, coalesced re-reload
requests, and terminal-state handling -- lives here once.  This mixin owns
every field that a scan produces (rows, warnings, load stamp, error text); the
host pane owns filter and selection state and supplies the repaint hooks
declared below.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from .project_inventory_types import InventoryIssue, InventoryLoadResult

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    # A real (empty) class rather than ``object``: a generic subclass whose only
    # explicit base is ``object`` cannot linearize against ``Generic``.
    class _MixinBase:
        pass


class InventoryLoadMixin[RecordT, IssueT: InventoryIssue](_MixinBase):
    """Run and consume background inventory scans for a cached pane."""

    if TYPE_CHECKING:

        def _apply_filters(self) -> None: ...

        def _refresh_options(self, *, preferred_id: str | None = None) -> None: ...

        def _update_summary(self) -> None: ...

        def _selected_record_id(self) -> str | None: ...

    _records: list[RecordT]
    _issues: list[IssueT]
    _loading: bool
    _reload_pending: bool
    _load_error: str
    _loaded_at: float
    _loaded_once: bool
    _worker: Worker[Any] | None

    def _init_inventory_load_state(self) -> None:
        """Initialize scan-produced state; call from the host's ``__init__``."""

        self._records = []
        self._issues = []
        self._loading = False
        self._reload_pending = False
        self._load_error = ""
        self._loaded_at = time.time()
        self._loaded_once = False
        self._worker = None

    def _start_inventory_load(self) -> None:
        if self._loading:
            self._reload_pending = True
            return
        self._prepare_inventory_load()
        self._loading = True
        self._load_error = ""
        self._update_summary()
        self._worker = self.run_worker(
            self._load_inventory,
            thread=True,
            exclusive=False,
            exit_on_error=False,
        )

    def _cancel_inventory_load(self) -> None:
        if self._worker is not None and not self._worker.is_finished:
            self._worker.cancel()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            selected = self._selected_record_id()
            result = event.worker.result
            self._loading = False
            if isinstance(result, InventoryLoadResult):
                self._records = list(result.records)
                self._issues = list(result.issues)
                self._loaded_at = result.loaded_at
                self._loaded_once = True
                self._apply_filters()
                self._refresh_options(preferred_id=selected)
            else:
                self._load_error = "inventory returned no result"
                self._update_summary()
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._load_error = (
                str(event.worker.error)
                if event.worker.error
                else "inventory load failed"
            )
            self._update_summary()
        elif event.state == WorkerState.CANCELLED:
            self._loading = False

        if (
            event.state
            in (
                WorkerState.SUCCESS,
                WorkerState.ERROR,
                WorkerState.CANCELLED,
            )
            and self._reload_pending
        ):
            self._reload_pending = False
            self.call_later(self._start_inventory_load)

    def _prepare_inventory_load(self) -> None:
        """Run cheap synchronous preparation immediately before worker launch."""

    def _load_inventory(self) -> InventoryLoadResult[RecordT, IssueT]:
        raise NotImplementedError


__all__ = ["InventoryLoadMixin"]
