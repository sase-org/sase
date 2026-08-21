from __future__ import annotations

from dataclasses import dataclass, field

from sase.ace.tui.proc_observer import ObservedProc
from sase.core.time import local_now


@dataclass
class ProcQueue:
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
