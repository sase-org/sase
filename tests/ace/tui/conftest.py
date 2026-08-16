"""Shared isolation for ACE TUI tests."""

import functools
import sys
import types
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from textual.pilot import Pilot

from sase.ace.testing import settle as settle_helpers
from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcLogLine,
    ProcLogStream,
)
from sase.ace.tui.util import shutdown
from sase.core.time import local_now
from sase.project_display_names import ProjectRefDisplaySnapshot


@dataclass
class _CompatProcQueue:
    _procs: dict[str, ObservedProc] = field(default_factory=dict)

    @property
    def running_count(self) -> int:
        return sum(1 for proc in self._procs.values() if proc.status == "running")

    def submit(
        self,
        proc_type: str,
        cl_name: str,
        project_file: str,
        **kwargs: object,
    ) -> ObservedProc:
        proc = ObservedProc(
            proc_id=f"{proc_type}-{len(self._procs)}",
            proc_type=proc_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=local_now(),
            display_name=kwargs.get("display_name")
            if isinstance(kwargs.get("display_name"), str)
            else None,
            dedup_key=kwargs.get("dedup_key")
            if isinstance(kwargs.get("dedup_key"), str)
            else None,
            exclusive_scopes=frozenset(
                str(item)
                for item in kwargs.get("exclusive_scopes", ())  # type: ignore[arg-type]
            ),
        )
        self._procs[proc.proc_id] = proc
        return proc

    def complete(
        self,
        proc_id: str,
        *,
        success: bool,
        message: str,
        output: str = "",
        error: str | None = None,
    ) -> None:
        proc = self._procs.get(proc_id)
        if proc is None:
            return
        proc.status = "success" if success else "error"
        proc.message = message
        proc.output = output
        proc.error = error
        proc.finished_at = local_now()

    def get(self, proc_id: str) -> ObservedProc | None:
        return self._procs.get(proc_id)

    def get_all(self) -> list[ObservedProc]:
        return list(self._procs.values())

    def remove(self, proc_id: str) -> None:
        self._procs.pop(proc_id, None)

    def remove_completed(self) -> None:
        self._procs = {
            proc_id: proc
            for proc_id, proc in self._procs.items()
            if proc.status == "running"
        }

    def get_running_for_cl(self, cl_name: str) -> ObservedProc | None:
        return next(
            (
                proc
                for proc in self._procs.values()
                if proc.status == "running" and proc.cl_name == cl_name
            ),
            None,
        )

    def get_running_for_key(self, dedup_key: str | None) -> ObservedProc | None:
        return next(
            (
                proc
                for proc in self._procs.values()
                if proc.status == "running" and proc.dedup_key == dedup_key
            ),
            None,
        )

    def get_running_for_scopes(self, scopes: object) -> ObservedProc | None:
        requested = frozenset(str(item) for item in scopes or ())  # type: ignore[arg-type]
        return next(
            (
                proc
                for proc in self._procs.values()
                if proc.status == "running" and requested & proc.exclusive_scopes
            ),
            None,
        )

    def prune_old(self) -> None:
        return None


_proc_queue_module = types.ModuleType("sase.ace.tui.proc_queue")
_proc_queue_module.ProcInfo = ObservedProc
_proc_queue_module.ProcLogLine = ProcLogLine
_proc_queue_module.ProcLogStream = ProcLogStream
_proc_queue_module.ProcQueue = _CompatProcQueue
sys.modules.setdefault("sase.ace.tui.proc_queue", _proc_queue_module)


@pytest.fixture(autouse=True)
def _reset_ace_shutdown_signal() -> Iterator[None]:
    shutdown._shutdown_signal.reset_for_tests()
    yield
    shutdown._shutdown_signal.reset_for_tests()


@pytest.fixture(autouse=True)
def _event_driven_bare_pilot_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make raw ACE TUI ``pilot.pause()`` calls use the shared settle barrier."""

    original_pause = Pilot.pause

    @functools.wraps(original_pause)
    async def pause(self: Pilot, delay: float | None = None) -> None:
        if delay is None:
            await settle_helpers.settle_pilot(self, _pilot_pause=original_pause)
        else:
            await original_pause(self, delay)

    monkeypatch.setattr(Pilot, "pause", pause)


@pytest.fixture(autouse=True)
def _isolate_commits_current_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ACE tests independent of the checkout running the test suite."""
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda **_kwargs: (None, None, None),
    )


@pytest.fixture(autouse=True)
def _isolate_commits_project_display_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep Stitches startup labels independent of the host project inventory."""
    monkeypatch.setattr(
        "sase.project_display_names.load_project_ref_display_snapshot",
        ProjectRefDisplaySnapshot,
    )
