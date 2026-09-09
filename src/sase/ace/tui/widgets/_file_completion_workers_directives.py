"""Directive-arg inventory workers for wait beads, finalizers, and machines."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._file_completion_worker_results import (
    FinalizerInventoryWorkerResult,
    MachineInventoryWorkerResult,
    WaitBeadInventoryWorkerResult,
)
from sase.ace.tui.widgets._file_completion_workers_artifacts import (
    FileCompletionArtifactInventoryWorkerMixin,
)


class FileCompletionDirectiveInventoryWorkerMixin(
    FileCompletionArtifactInventoryWorkerMixin
):
    """Mixin providing directive-arg inventory loading."""

    if TYPE_CHECKING:
        _file_completion_active: bool
        _completion_kind: str
        _wait_bead_inventory: tuple[dict[str, str], ...] | None
        _wait_bead_available: bool
        _wait_bead_project: str | None
        _wait_bead_inflight: set[str]
        _finalizer_inventory: tuple[dict[str, object], ...] | None
        _finalizer_available: bool
        _finalizer_inflight: bool
        _machine_inventory: tuple[dict[str, str], ...] | None
        _machine_available: bool
        _machine_inflight: bool

        def _refresh_file_completion_from_cursor(self) -> None: ...
        def _wait_bead_project_key(self) -> str | None: ...

    def _schedule_wait_bead_inventory_load(self, project_key: str) -> None:
        """Coalesce one bead-store read on a background worker."""
        if project_key in self._wait_bead_inflight:
            return
        self._wait_bead_inflight.add(project_key)

        def task() -> WaitBeadInventoryWorkerResult:
            from sase.ace.tui.models.wait_bead_catalog import raw_wait_bead_inventory

            try:
                rows, available = raw_wait_bead_inventory(project_key)
            except Exception:  # noqa: BLE001 - degrade rather than freeze the prompt.
                rows, available = (), False
            return WaitBeadInventoryWorkerResult(
                project_key=project_key,
                rows=rows,
                available=available,
            )

        self.run_worker(
            task,
            name=f"prompt-wait-beads:{project_key}",
            group="prompt-wait-beads",
            thread=True,
        )

    def _apply_wait_bead_inventory_result(
        self,
        result: WaitBeadInventoryWorkerResult,
    ) -> None:
        """Store a warm bead inventory and refresh a matching open menu."""
        self._wait_bead_inventory = result.rows
        self._wait_bead_available = result.available
        self._wait_bead_project = result.project_key
        if not self._file_completion_active or self._completion_kind != "directive_arg":
            return
        if self._wait_bead_project_key() != result.project_key:
            return
        self._refresh_file_completion_from_cursor()

    def on_mount(self) -> None:
        """Warm the finalizer catalog as soon as a prompt pane is live."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._schedule_finalizer_inventory_load()

    def _prompt_app_or_none(self) -> object | None:
        """Return the hosting app when one is active."""
        try:
            return self.app
        except Exception:
            return None

    def _schedule_finalizer_inventory_load(self) -> None:
        """Coalesce one finalizer-config replay on a background worker."""
        if callable(getattr(self._prompt_app_or_none(), "finalizer_inventory", None)):
            return
        if self._finalizer_inflight:
            return
        self._finalizer_inflight = True

        def task() -> FinalizerInventoryWorkerResult:
            from sase.finalizers.catalog import build_finalizer_completion_catalog

            try:
                catalog = build_finalizer_completion_catalog()
            except Exception:  # noqa: BLE001 - degrade rather than freeze the prompt.
                return FinalizerInventoryWorkerResult(rows=(), available=False)
            if not catalog.ok:
                return FinalizerInventoryWorkerResult(rows=(), available=False)
            return FinalizerInventoryWorkerResult(
                rows=catalog.wire_entries(),
                available=True,
            )

        self.run_worker(
            task,
            name="prompt-finalizers",
            group="prompt-finalizers",
            thread=True,
        )

    def _apply_finalizer_inventory_result(
        self,
        result: FinalizerInventoryWorkerResult,
    ) -> None:
        """Store a warm catalog and refresh a still-current ``%final`` menu."""
        self._finalizer_inventory = result.rows
        self._finalizer_available = result.available
        if not self._file_completion_active or self._completion_kind != "directive_arg":
            return
        clause_ctx = self._directive_clause_at_cursor()
        if clause_ctx is None:
            return
        from sase.ace.tui.widgets.directive_completion import (
            clause_needs_finalizer_inventory,
        )

        _row, clause = clause_ctx
        if not clause_needs_finalizer_inventory(clause):
            return
        self._refresh_file_completion_from_cursor()

    def _schedule_machine_inventory_load(self) -> None:
        """Coalesce one dispatch-machine config read on a background worker."""
        if self._machine_inflight:
            return
        self._machine_inflight = True

        def task() -> MachineInventoryWorkerResult:
            from sase.dispatch.machine_catalog import machine_completion_catalog_payload

            try:
                payload = machine_completion_catalog_payload()
            except Exception:  # noqa: BLE001 - degrade rather than freeze the prompt.
                return MachineInventoryWorkerResult(rows=(), available=False)
            entries = payload.get("entries")
            if not isinstance(entries, list):
                return MachineInventoryWorkerResult(rows=(), available=False)
            rows: list[dict[str, str]] = []
            for entry in entries:
                if isinstance(entry, dict):
                    rows.append(
                        {
                            key: str(value)
                            for key, value in entry.items()
                            if isinstance(key, str)
                        }
                    )
            return MachineInventoryWorkerResult(
                rows=tuple(rows),
                available=True,
            )

        self.run_worker(
            task,
            name="prompt-dispatch-machines",
            group="prompt-dispatch-machines",
            thread=True,
        )

    def _apply_machine_inventory_result(
        self,
        result: MachineInventoryWorkerResult,
    ) -> None:
        """Store a warm machine catalog and refresh a matching open menu."""
        self._machine_inventory = result.rows
        self._machine_available = result.available
        if not self._file_completion_active or self._completion_kind != "directive_arg":
            return
        clause_ctx = self._directive_clause_at_cursor()
        if clause_ctx is None:
            return
        from sase.ace.tui.widgets.directive_completion import (
            clause_needs_machine_inventory,
        )

        _row, clause = clause_ctx
        if not clause_needs_machine_inventory(clause):
            return
        self._refresh_file_completion_from_cursor()
