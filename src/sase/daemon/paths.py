"""Path and environment helpers for the local SASE daemon."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

SOCKET_FILENAME = "sase-daemon.sock"
LOCK_FILENAME = "daemon.lock"
LOCK_METADATA_FILENAME = "daemon.lock.json"
LOG_FILENAME = "daemon.log"
PROJECTION_DB_RELATIVE_PATH = Path("projections") / "projection.sqlite"

SOURCE_ROOT_NAMES = (
    "projects",
    "notifications",
    "pending_actions",
    "artifacts",
    "chats",
    "beads",
    "repos",
    "workflow_state",
    "telegram",
    "mobile_gateway",
)


def default_socket_path(
    *,
    sase_home: str | Path | None = None,
    host_identity: str | None = None,
) -> Path:
    home = _default_sase_home() if sase_home is None else Path(sase_home)
    host = sanitize_host_identity(
        host_identity if host_identity is not None else os.environ.get("HOSTNAME")
    )
    return default_run_root(home, host) / SOCKET_FILENAME


def default_run_root(sase_home: str | Path, host_identity: str | None) -> Path:
    return Path(sase_home) / "run" / sanitize_host_identity(host_identity)


def _default_projection_db_path(run_root: str | Path) -> Path:
    return Path(run_root) / PROJECTION_DB_RELATIVE_PATH


def storage_layout_diagnostics(
    *,
    sase_home: str | Path,
    run_root: str | Path,
    socket_path: str | Path,
    host_identity: str | None,
) -> dict[str, Any]:
    """Return stable storage-layout diagnostics shared by status/doctor JSON."""
    home = Path(sase_home)
    run = Path(run_root)
    socket = Path(socket_path)
    default_run = default_run_root(home, host_identity)
    projection = _default_projection_db_path(run)
    log = run / LOG_FILENAME
    source_roots = [home / name for name in SOURCE_ROOT_NAMES]
    paths = {
        "sase_home": _path_entry(home, "source_root"),
        "run_root": _path_entry(
            run, _classify_path(run, home, run, default_run, source_roots)
        ),
        "socket_path": _path_entry(
            socket, _classify_path(socket, home, run, default_run, source_roots)
        ),
        "projection_db_path": _path_entry(
            projection,
            _classify_path(projection, home, run, default_run, source_roots),
        ),
        "log_path": _path_entry(
            log, _classify_path(log, home, run, default_run, source_roots)
        ),
    }
    runtime_files = [
        socket,
        run / LOCK_FILENAME,
        run / LOCK_METADATA_FILENAME,
        log,
        projection,
        projection.with_name(projection.name + "-wal"),
        projection.with_name(projection.name + "-shm"),
        run / "checkpoints",
        run / "backups",
        run / "queues",
    ]
    warnings = _layout_warnings(
        home=home,
        run_root=run,
        socket_path=socket,
        default_run_root=default_run,
        source_roots=source_roots,
        paths=paths,
    )
    return {
        "schema_version": 1,
        **paths,
        "source_roots": [_path_entry(path, "source_root") for path in source_roots],
        "runtime_files": [str(path) for path in runtime_files],
        "warnings": warnings,
    }


def daemon_disabled(args: Any | None = None) -> bool:
    """Shared hook for future commands that expose ``--no-daemon``."""
    arg_value = bool(getattr(args, "no_daemon", False)) if args is not None else False
    env_value = os.environ.get("SASE_NO_DAEMON", "").strip().lower()
    return arg_value or env_value in {"1", "true", "yes", "on"}


def _default_sase_home() -> Path:
    if value := os.environ.get("SASE_HOME"):
        return Path(value)
    if value := os.environ.get("HOME"):
        return Path(value) / ".sase"
    return Path(".sase")


def sanitize_host_identity(value: str | None) -> str:
    if value is None or not value.strip():
        return "sase-host"
    sanitized = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in ".-_") else "-"
        for ch in value.strip()
    ).strip("-")
    return sanitized or "sase-host"


def _path_entry(path: Path, path_kind: str) -> dict[str, str]:
    return {"path": str(path), "path_kind": path_kind}


def _classify_path(
    path: Path,
    sase_home: Path,
    run_root: Path,
    default_run_root: Path,
    source_roots: list[Path],
) -> str:
    if path == sase_home or any(_starts_with(path, root) for root in source_roots):
        return "source_root"
    if _starts_with(path, default_run_root):
        return "host_local_default"
    if _starts_with(path, run_root):
        return "host_local_override"
    if _starts_with(path, sase_home) and not _starts_with(path, sase_home / "run"):
        return "unsafe_synced_candidate"
    if _starts_with(path, sase_home / "run"):
        return "host_local_override"
    return "unknown"


def _layout_warnings(
    *,
    home: Path,
    run_root: Path,
    socket_path: Path,
    default_run_root: Path,
    source_roots: list[Path],
    paths: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if run_root != default_run_root:
        warnings.append(
            {
                "id": "run_root_override",
                "severity": "warning",
                "path": str(run_root),
                "message": (
                    "run_root is not the default host-local directory; "
                    "ensure it is excluded from sync"
                ),
            }
        )
    if any(_starts_with(run_root, root) for root in source_roots):
        warnings.append(
            {
                "id": "run_root_under_source_root",
                "severity": "error",
                "path": str(run_root),
                "message": (
                    "run_root is under a source store; move daemon runtime "
                    "files out of synced source state"
                ),
            }
        )
    if not _starts_with(socket_path, run_root):
        warnings.append(
            {
                "id": "socket_outside_run_root",
                "severity": "warning",
                "path": str(socket_path),
                "message": (
                    "socket_path is outside run_root; keep sockets and locks host-local"
                ),
            }
        )
    for name, entry in paths.items():
        if entry["path_kind"] == "unsafe_synced_candidate":
            warnings.append(
                {
                    "id": f"{name}_unsafe_synced_candidate",
                    "severity": "error",
                    "path": entry["path"],
                    "message": (
                        f"{name} looks like it lives in synced source state; "
                        "exclude daemon runtime files from sync"
                    ),
                }
            )
    if _starts_with(run_root, home) and not _starts_with(run_root, home / "run"):
        warnings.append(
            {
                "id": "run_root_under_sase_home_non_run",
                "severity": "error",
                "path": str(run_root),
                "message": "run_root under sase_home should live below run/<host>",
            }
        )
    return warnings


def _starts_with(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
