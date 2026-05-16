"""Apply-layer rebuild scheduling for Phase 3 of ``sase-3r``.

When the Tier 1 loader returns ``index_missing=True`` (the visibility-
aware index file is absent), the apply layer must spawn a one-off
artifact-index rebuild worker rather than triggering a Tier 2 source
scan. Duplicate calls while a rebuild is already in flight coalesce.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agents._loading_disk import AgentLoadingDiskMixin


class _RebuildFakeApp(AgentLoadingDiskMixin):
    """Fake app exposing only the attributes ``_schedule_artifact_index_rebuild`` reads."""

    def __init__(self) -> None:
        self._artifact_index_rebuild_in_flight = False
        self._scheduled_refreshes: int = 0
        self._workers: list[Any] = []

    def run_worker(  # noqa: D401 - mirror Textual signature
        self,
        coroutine: Any,
        *,
        exclusive: bool = False,
        group: str = "",
    ) -> None:
        del exclusive, group
        self._workers.append(coroutine)

    def _schedule_agents_async_refresh(self) -> None:
        self._scheduled_refreshes += 1


def test_schedule_rebuild_spawns_worker_and_marks_in_flight() -> None:
    app = _RebuildFakeApp()
    app._schedule_artifact_index_rebuild()
    assert len(app._workers) == 1
    assert app._artifact_index_rebuild_in_flight is True
    # Drop the coroutine so the asyncio "never awaited" warning doesn't fire.
    coroutine = app._workers[0]
    coroutine.close()


def test_schedule_rebuild_coalesces_while_in_flight() -> None:
    app = _RebuildFakeApp()
    app._artifact_index_rebuild_in_flight = True

    app._schedule_artifact_index_rebuild()
    assert app._workers == []


def test_schedule_rebuild_without_run_worker_is_a_noop() -> None:
    app = _RebuildFakeApp()
    # Simulate an environment (test fake) without Textual's run_worker.
    object.__setattr__(app, "run_worker", None)

    app._schedule_artifact_index_rebuild()

    assert app._artifact_index_rebuild_in_flight is False
