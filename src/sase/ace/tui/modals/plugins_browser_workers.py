"""Load and worker-event orchestration for the Config Center Updates pane."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Literal

from textual.worker import Worker, WorkerState

from .plugins_browser_loading import PluginsLoadResult

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from rich.console import RenderableType

    from .plugins_browser_rows import UpdateRow
else:
    _MixinBase = object


_FRESH_EDITABLE_ROOTS_TTL_SECONDS = 60.0


class PluginsBrowserWorkersMixin(_MixinBase):
    """Load shared inventory and dispatch results from every pane worker."""

    if TYPE_CHECKING:
        _rows: tuple[UpdateRow, ...]
        _rows_by_key: dict[str, UpdateRow]
        _agent_cli_colors: dict[str, str]
        _agent_cli_error: str | None
        _agent_cli_history: tuple[Any, ...]
        _agent_cli_history_config: Any
        _agent_cli_history_error: str | None
        _agent_cli_plan_worker: Worker[Any] | None
        _agent_cli_statuses: tuple[Any, ...]
        _catalog: Any
        _core_incoming_commits: dict[str, Any]
        _core_versions: Any
        _dev_root: str | None
        _error: str | None
        _fresh_editable_roots_evidence: tuple[frozenset[str], float] | None
        _incoming_commit_workers: dict[int, Any]
        _plugin_latest_workers: dict[int, str]
        _incoming_commits_enabled: bool
        _incoming_commits_limit: int
        _install_mode: str | None
        _loading: bool
        _mode_switch_plan_worker: Worker[Any] | None
        _now: float
        _offline: bool
        _plan_worker: Worker[Any] | None
        _restore_key: str | None
        _sase_update_plan_worker: Worker[Any] | None
        _session_state: Any
        _uninstall_plan_worker: Worker[Any] | None
        _update_plan_worker: Worker[Any] | None
        _updates_loaded_once: bool
        _uv_tool: Any
        _worker: Worker[Any] | None
        app: Any

        def _highlighted_row(self) -> UpdateRow | None: ...

        def _hints(self) -> str: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _on_agent_cli_update_preview(self, result: Any) -> None: ...

        def _on_incoming_commits_worker_state(
            self, event: Worker.StateChanged, key: Any
        ) -> None: ...

        def _on_plugin_latest_worker_state(
            self, event: Worker.StateChanged, key: str
        ) -> None: ...

        def _on_install_preview(self, result: Any) -> None: ...

        def _on_mode_switch_preview(self, result: Any) -> None: ...

        def _on_sase_update_preview(self, result: Any) -> None: ...

        def _on_uninstall_preview(self, result: Any) -> None: ...

        def _on_update_preview(self, result: Any) -> None: ...

        def _render_all(self) -> None: ...

        def _sync_header(self) -> None: ...

        def _sync_state_visibility(self) -> None: ...

        def _update_static(self, selector: str, content: RenderableType) -> None: ...

        def _worker_error_text(self, worker: Any, *, kind: str = ...) -> str: ...

    def _start_load(self, *, force: bool) -> None:
        from . import plugins_browser_pane as pane_module

        prior_uv_tool = self._uv_tool
        self._loading = True
        self._error = None
        # A reload invalidates the prior handoff immediately. Only this load's
        # successful online result may establish new evidence.
        self._fresh_editable_roots_evidence = None
        # Re-highlight whatever is selected now once the reload lands so a
        # refresh / offline toggle doesn't snap the user back to the top.
        highlighted = self._highlighted_row()
        self._restore_key = (
            highlighted.key
            if highlighted is not None
            else self._session_state.rows.identity
        )
        self._core_incoming_commits = {}
        self._sync_state_visibility()
        self._sync_header()
        self._update_static("#updates-hints", self._hints())
        refresh = force
        offline = self._offline
        incoming_commits_enabled = self._incoming_commits_enabled
        incoming_commits_limit = self._incoming_commits_limit
        agent_cli_history_enabled = self._agent_cli_history_config.enabled

        def task() -> PluginsLoadResult:
            result = pane_module._load_plugins_catalog(
                refresh=refresh,
                offline=offline,
                incoming_commits_enabled=incoming_commits_enabled,
                incoming_commits_limit=incoming_commits_limit,
                agent_cli_history_enabled=agent_cli_history_enabled,
            )
            # Building rows here (off the event loop) rather than on receipt
            # keeps construction off the UI thread; every existing loader stub
            # keeps working unchanged because rows are derived from whatever
            # it returned.
            rows = pane_module._build_update_rows(
                result,
                uv_tool=getattr(result, "uv_tool", None) or prior_uv_tool,
                offline=offline,
            )
            if dataclasses.is_dataclass(result) and not isinstance(result, type):
                return dataclasses.replace(result, rows=rows)
            result.rows = rows
            return result

        self._worker = self.run_worker(
            task, thread=True, exclusive=True, exit_on_error=False
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        incoming_key = self._incoming_commit_workers.get(id(event.worker))
        if incoming_key is not None:
            self._on_incoming_commits_worker_state(event, incoming_key)
            return
        latest_key = self._plugin_latest_workers.get(id(event.worker))
        if latest_key is not None:
            self._on_plugin_latest_worker_state(event, latest_key)
            return
        if event.worker is self._plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._plan_worker = None
                self._on_install_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._plan_worker = None
                self._notify(self._worker_error_text(event.worker), severity="error")
            return
        if event.worker is self._update_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._update_plan_worker = None
                self._on_update_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._update_plan_worker = None
                self._notify(
                    self._worker_error_text(event.worker, kind="update"),
                    severity="error",
                )
            return
        if event.worker is self._uninstall_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._uninstall_plan_worker = None
                self._on_uninstall_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._uninstall_plan_worker = None
                self._notify(
                    self._worker_error_text(event.worker, kind="uninstall"),
                    severity="error",
                )
            return
        if event.worker is self._sase_update_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._sase_update_plan_worker = None
                self._on_sase_update_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._sase_update_plan_worker = None
                self._notify(
                    self._worker_error_text(event.worker, kind="sase update"),
                    severity="error",
                )
            return
        if event.worker is self._mode_switch_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._mode_switch_plan_worker = None
                self._on_mode_switch_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._mode_switch_plan_worker = None
                self._notify(
                    self._worker_error_text(event.worker, kind="mode switch"),
                    severity="error",
                )
            return
        if event.worker is self._agent_cli_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._agent_cli_plan_worker = None
                self._on_agent_cli_update_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._agent_cli_plan_worker = None
                self._notify(
                    self._worker_error_text(event.worker, kind="agent CLI update"),
                    severity="error",
                )
            return
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._loading = False
            self._updates_loaded_once = True
            self._catalog = getattr(result, "catalog", None)
            self._error = getattr(result, "error", None)
            self._now = getattr(result, "now", self._now)
            fresh_roots = frozenset(getattr(result, "fresh_editable_roots", ()))
            self._fresh_editable_roots_evidence = None
            if self._error is None and not self._offline and fresh_roots:
                from . import plugins_browser_pane as pane_module

                self._fresh_editable_roots_evidence = (
                    fresh_roots,
                    pane_module._monotonic(),
                )
            # Keep a previously-detected probe result if a stubbed loader (or a
            # failed probe) returns None -- "detect once" per the epic.
            probed = getattr(result, "uv_tool", None)
            if probed is not None:
                self._uv_tool = probed
            core_versions = getattr(result, "core_versions", None)
            if core_versions is not None:
                self._core_versions = core_versions
            install_mode = getattr(result, "install_mode", None)
            if install_mode is not None:
                self._install_mode = install_mode
            dev_root = getattr(result, "dev_root", None)
            if dev_root is not None:
                self._dev_root = dev_root
            self._core_incoming_commits = dict(
                getattr(result, "core_incoming_commits", {}) or {}
            )
            self._agent_cli_statuses = tuple(
                getattr(result, "agent_cli_statuses", ()) or ()
            )
            self._agent_cli_error = getattr(result, "agent_cli_error", None)
            self._agent_cli_colors = dict(getattr(result, "agent_cli_colors", {}) or {})
            self._agent_cli_history = tuple(
                getattr(result, "agent_cli_history", ()) or ()
            )
            self._agent_cli_history_error = getattr(
                result, "agent_cli_history_error", None
            )
            self._rows = tuple(getattr(result, "rows", ()))
            self._rows_by_key = {row.key: row for row in self._rows}
            self._render_all()
            update_status = getattr(result, "update_status", None)
            refresh_indicator = getattr(
                self.app,
                "_schedule_updates_indicator_revalidation",
                None,
            )
            if update_status is not None and callable(refresh_indicator):
                refresh_indicator(update_status)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._fresh_editable_roots_evidence = None
            self._error = (
                str(event.worker.error) if event.worker.error else "load failed"
            )
            self._core_incoming_commits = {}
            self._render_all()

    def _reusable_fresh_editable_roots(
        self,
        *,
        now: float | None = None,
        ttl_seconds: float = _FRESH_EDITABLE_ROOTS_TTL_SECONDS,
    ) -> frozenset[str]:
        """Return load-refreshed roots while their short handoff is fresh."""
        from . import plugins_browser_pane as pane_module

        evidence = self._fresh_editable_roots_evidence
        if evidence is None:
            return frozenset()
        roots, completed_at = evidence
        current = pane_module._monotonic() if now is None else now
        age = current - completed_at
        if 0.0 <= age <= ttl_seconds:
            return roots
        return frozenset()
