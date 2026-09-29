"""Output-of-record path resolution for ``sase tool`` runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def output_paths_for_run(run: dict[str, Any]) -> list[Path]:
    """Return the output-of-record paths for *run*, in read order."""

    logs = run.get("logs")
    logs_map = logs if isinstance(logs, dict) else {}
    owner_log = logs_map.get("owner_log_path")
    if owner_log:
        return [Path(str(owner_log))]
    kind = str(run.get("owner_kind") or "")
    owner_id = str(run.get("owner_id") or "")
    if kind == "proc" and owner_id:
        try:
            from sase.procs.store import get_proc

            proc = get_proc(owner_id)
        except Exception:  # noqa: BLE001 - fall through to retained logs.
            proc = None
        if proc is not None and proc.log_path:
            return [Path(proc.log_path)]
    if kind == "monitor" and owner_id:
        path = monitor_output_path(run, owner_id)
        if path is not None:
            return [path]
    paths: list[Path] = []
    for key in ("stdout_path", "stderr_path"):
        raw = logs_map.get(key)
        if raw:
            paths.append(Path(str(raw)))
    return paths


def monitor_output_path(run: dict[str, Any], monitor_id: str) -> Path | None:
    try:
        from sase.monitor.logs import monitor_log_path
        from sase.monitor.store import list_monitors, resolve_monitor_ref
    except Exception:  # noqa: BLE001 - no monitor reader available.
        return None
    try:
        records = list_monitors(project=str(run.get("project") or "") or None)
        record = resolve_monitor_ref(monitor_id, records)
    except Exception:  # noqa: BLE001 - linked-repo runs retry unscoped.
        try:
            record = resolve_monitor_ref(monitor_id, list_monitors())
        except Exception:  # noqa: BLE001 - expired owners have no log.
            return None
    raw = record.output_path or None
    if raw:
        return Path(raw)
    try:
        return Path(monitor_log_path(record.artifacts_dir))
    except Exception:  # noqa: BLE001 - unresolvable log path.
        return None


__all__ = [
    "monitor_output_path",
    "output_paths_for_run",
]
