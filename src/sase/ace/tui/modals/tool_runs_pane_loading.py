"""Async loading for the Admin Center Tools pane (sase-1bt.10).

Read-only project/machine views over the machine-local ToolRun ledger.
Never reconciles, never settles, never shells out on a UI path.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from ._tool_runs_pane_shared import store_token
from .tool_runs_pane_data import filter_briefs, order_runs

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from .config_center_session import ToolRunsSessionState
else:
    _MixinBase = object

_RUNS_LIMIT = 100


class ToolRunsPaneLoadingMixin(_MixinBase):
    """Reload runs, failures, and catalog off the UI thread."""

    if TYPE_CHECKING:
        _all_projects: bool
        _catalog_entries: list[Any]
        _catalog_project: str
        _catalog_summaries: dict[str, dict[str, Any]]
        _detail_cache: dict[str, Any]
        _failure_groups: list[dict[str, Any]]
        _last_token: tuple[object, ...]
        _loaded_once: bool
        _loading: bool
        _query: str
        _reload_pending: bool
        _run_briefs: list[Any]
        _run_rows: list[tuple[str, Any]]
        _scope_project: str | None
        _session_state: ToolRunsSessionState
        _tab_active: bool

        def _is_active_tab(self) -> bool: ...

        def _rebuild_list(self) -> None: ...

        def _render_detail(self) -> None: ...

    def _request_reload(self, *, force: bool = False) -> None:
        if self._loading:
            self._reload_pending = True
            return
        self._loading = True
        self._reload_pending = False
        if force:
            self._detail_cache.clear()
        self.run_worker(
            self._load_async(force=force),
            exclusive=True,
            group="tools-pane-load",
        )

    async def _load_async(self, *, force: bool) -> None:
        try:
            await asyncio.to_thread(self._load_sync)
        except Exception:
            pass
        finally:
            self._loading = False
        try:
            self._rebuild_list()
            self._render_detail()
        except Exception:
            pass
        self._loaded_once = True
        if self._reload_pending:
            self._reload_pending = False
            self._request_reload()

    def _load_sync(self) -> None:
        project = None if self._all_projects else self._scope_project
        self._load_runs(project)
        self._load_failures(project)
        self._load_catalog()

    def _load_runs(self, project: str | None) -> None:
        try:
            from sase.core.tool_run import tool_run_briefs, tool_run_live_glance
        except Exception:
            self._run_rows = []
            self._run_briefs = []
            return
        try:
            glance = tool_run_live_glance()
            live_by_id = {run.run_id: run for run in glance.runs}
            silent_after = int(getattr(glance, "silent_after_s", 60) or 60)
        except Exception:
            live_by_id = {}
            silent_after = 60
        try:
            request: dict[str, Any] = {"limit": _RUNS_LIMIT}
            if project is not None:
                request["project"] = project
            briefs = tool_run_briefs(request)
            rows = list(briefs.runs)
        except Exception:
            rows = []
        filtered = filter_briefs(list(rows), self._query, project=None)
        now_ts = int(time.time())
        self._run_briefs = [
            brief
            for _, brief in order_runs(
                filtered, live_by_id, now_ts=now_ts, silent_after_s=silent_after
            )
        ]
        self._run_rows = order_runs(
            filtered, live_by_id, now_ts=now_ts, silent_after_s=silent_after
        )

    def _load_failures(self, project: str | None) -> None:
        try:
            from sase.core.tool_run import tool_run_failures
        except Exception:
            self._failure_groups = []
            return
        try:
            request: dict[str, Any] = {"days": 7, "limit": 50, "runs_limit": 20}
            if project is not None:
                request["project"] = project
            try:
                result = tool_run_failures(request)
            except Exception:
                # Pinned core without the opt-in field: fall back to the
                # counts plus last_run_id/newest_owners shape.
                fallback = dict(request)
                fallback.pop("runs_limit", None)
                result = tool_run_failures(fallback)
            groups = result.get("groups", ())
            self._failure_groups = [
                dict(group) for group in groups if isinstance(group, dict)
            ]
        except Exception:
            self._failure_groups = []

    def _load_catalog(self) -> None:
        try:
            from sase.config.tools import load_project_tool_catalog_at
            from sase.core.tool_run import tool_run_summary
        except Exception:
            self._catalog_entries = []
            return
        try:
            from sase.ace.tui.actions.agents._tool_run_actions import (
                primary_checkout_root,
            )

            root = primary_checkout_root(self._scope_project) or None
        except Exception:
            root = None
        try:
            catalog = load_project_tool_catalog_at(root)
        except Exception:
            self._catalog_entries = []
            return
        self._catalog_entries = list(catalog.entries)
        self._catalog_project = str(getattr(catalog, "project", "") or "")
        summaries: dict[str, dict[str, Any]] = {}
        for entry in self._catalog_entries[:50]:
            try:
                summaries[entry.name] = tool_run_summary(
                    {
                        "schema_version": 1,
                        "project": catalog.project,
                        "tool_name": entry.name,
                        "definition_digest": entry.digest,
                    }
                )
            except Exception:
                continue
        self._catalog_summaries = summaries

    def _on_poll_tick(self) -> None:
        if not self._is_active_tab() and self._tab_active is False:
            pass
        token = store_token()
        if token == self._last_token:
            return
        self._last_token = token
        if self._is_active_tab() or self._tab_active:
            self._request_reload()


__all__ = ["ToolRunsPaneLoadingMixin"]
