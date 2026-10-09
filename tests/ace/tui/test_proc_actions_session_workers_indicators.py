"""Tools/bg indicator count and update-lane coverage."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.proc_actions import ProcActionsMixin
from sase.ace.tui.proc_observer import ObservedProc, ProcProjection
from sase.core.time import local_now
from tests.ace.tui._proc_actions_session_workers_shared import durable_row, sync_row

__all__ = [
    "test_update_proc_indicator_missing_proc_indicator_is_noop",
    "test_update_proc_indicator_moves_update_lane_to_green_gear",
    "test_update_proc_indicator_splits_ace_and_monitor_counts",
]


class _FakeBgIndicator:
    def __init__(self) -> None:
        self.models: list[tuple[int, str]] = []

    def set_model(self, bg_count: int, tooltip: str) -> None:
        self.models.append((bg_count, tooltip))


class _FakeToolsIndicator:
    def __init__(self) -> None:
        self.models: list[Any] = []

    def set_model(self, model: Any) -> None:
        self.models.append(model)


class _IndicatorHost(ProcActionsMixin):
    """Exercises the real ``_update_proc_indicator`` logic."""

    def __init__(
        self,
        projection: ProcProjection,
        *,
        widgets: dict[str, Any] | None = None,
    ) -> None:
        self._proc_projection = projection
        self._session_completion_callbacks: dict[str, Any] = {}
        self._widgets = widgets if widgets is not None else {}

    def query_one(self, selector: str, _type: Any = None) -> Any:
        widget = self._widgets.get(selector)
        if widget is None:
            raise LookupError(selector)
        return widget


class _FakeUpdatesIndicator:
    def __init__(self) -> None:
        self.labels: list[tuple[str, ...]] = []

    def set_running(self, labels: object) -> None:
        self.labels.append(tuple(labels))  # type: ignore[arg-type]


def _update_row(proc_id: str) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type="sase-update",
        cl_name="",
        project_file="",
        status="running",
        message="running",
        started_at=local_now(),
        display_name="sase update",
    )


def test_update_proc_indicator_splits_ace_and_monitor_counts() -> None:
    proc_indicator = _FakeBgIndicator()
    tools_indicator = _FakeToolsIndicator()
    host = _IndicatorHost(
        ProcProjection(
            rows=(
                durable_row(scope="a"),
                durable_row(scope="b"),
                ObservedProc(
                    proc_id="monitor-1",
                    proc_type="detached",
                    cl_name="sase",
                    project_file="",
                    status="running",
                    message="running",
                    started_at=local_now(),
                    origin="monitor",
                ),
            ),
            active_count=3,
            active_monitor_count=1,
        ),
        widgets={
            "#proc-indicator": proc_indicator,
            "#tools-indicator": tools_indicator,
        },
    )

    host._update_proc_indicator()

    assert [count for count, _tooltip in proc_indicator.models] == [2]
    assert proc_indicator.models[0][1].startswith("2 TUI background procs")
    assert len(tools_indicator.models) == 1


def test_update_proc_indicator_missing_proc_indicator_is_noop() -> None:
    host = _IndicatorHost(
        ProcProjection(active_count=2, active_monitor_count=1),
        widgets={},
    )

    host._update_proc_indicator()


def test_update_proc_indicator_moves_update_lane_to_green_gear() -> None:
    proc_indicator = _FakeBgIndicator()
    updates_indicator = _FakeUpdatesIndicator()
    host = _IndicatorHost(
        ProcProjection(rows=(_update_row("update-1"),)),
        widgets={
            "#proc-indicator": proc_indicator,
            "#updates-indicator": updates_indicator,
        },
    )

    host._update_proc_indicator()

    assert [count for count, _tooltip in proc_indicator.models] == [0]
    assert updates_indicator.labels == [("sase update",)]

    host._proc_projection = ProcProjection(
        rows=(_update_row("update-1"), sync_row("sync-1")),
    )
    host._update_proc_indicator()

    assert proc_indicator.models[-1][0] == 1
    assert updates_indicator.labels[-1] == ("sase update",)

    host._proc_projection = ProcProjection(rows=(sync_row("sync-1"),))
    host._update_proc_indicator()

    assert proc_indicator.models[-1][0] == 1
    assert updates_indicator.labels[-1] == ()
