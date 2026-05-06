"""Startup contract sentinel for the artifact graph benchmark."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.startup import StartupMixin

from .records import query_record


class _StartupSentinelApp(StartupMixin):
    """Minimal host for the post-mount startup contract."""

    def __init__(self) -> None:
        self._post_mount_background_loads_started = False
        self._fs_watcher = None
        self.worker_calls: list[dict[str, Any]] = []
        self.watcher_start_calls = 0

    def run_worker(self, worker: Any, **kwargs: Any) -> None:
        self.worker_calls.append({"worker": worker, "kwargs": kwargs})

    def _run_agents_async_refresh(self) -> None:
        raise AssertionError("startup sentinel must schedule, not run, agents")

    def _run_axe_startup_init(self) -> None:
        raise AssertionError("startup sentinel must schedule, not run, axe")

    def _start_artifact_watcher(self) -> None:
        self.watcher_start_calls += 1


def measure_startup_contract_sentinel(
    *,
    operation: str = "startup_contract:no_broad_artifact_graph_calls",
    fixture: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Verify post-mount startup scheduling does not touch graph queries."""

    app = _StartupSentinelApp()
    broad_calls: list[str] = []

    def record_call(name: str) -> Any:
        def _inner(*args: Any, **kwargs: Any) -> None:
            del args, kwargs
            broad_calls.append(name)

        return _inner

    start = time.perf_counter()
    with (
        patch(
            "sase.core.artifact_facade.artifact_rebuild",
            record_call("artifact_rebuild"),
        ),
        patch(
            "sase.core.artifact_facade.artifact_list",
            record_call("artifact_list"),
        ),
        patch(
            "sase.core.artifact_facade.artifact_search",
            record_call("artifact_search"),
        ),
        patch(
            "sase.core.artifact_facade.artifact_show",
            record_call("artifact_show"),
        ),
        patch(
            "sase.core.artifact_facade.artifact_show_paged",
            record_call("artifact_show_paged"),
        ),
        patch(
            "sase.core.artifact_facade.artifact_summary",
            record_call("artifact_summary"),
        ),
    ):
        app._start_post_mount_background_loads()
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    errors: list[str] = []
    if broad_calls:
        errors.append(f"unexpected artifact graph startup calls: {broad_calls}")
    if len(app.worker_calls) != 2:
        errors.append(f"unexpected startup workers: {len(app.worker_calls)}")
    if app.watcher_start_calls != 1:
        errors.append(f"unexpected watcher starts: {app.watcher_start_calls}")

    return query_record(
        operation,
        elapsed_ms,
        fixture={
            "workers": len(app.worker_calls),
            "watcher_starts": 1,
            **(fixture or {}),
        },
        bounded=True,
        query_count=len(broad_calls),
        result_count=len(app.worker_calls),
        errors=errors,
    )
