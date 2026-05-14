"""Daemon metadata and health inspection helpers."""

from __future__ import annotations

import argparse
import fcntl
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.integrations._daemon_lifecycle_config import (
    host_identity_from_env,
    runtime_paths_from_args,
)
from sase.integrations._daemon_lifecycle_process import process_is_live
from sase.integrations._daemon_lifecycle_types import (
    LOCK_SCHEMA_VERSION,
    DaemonInspection,
    DaemonRuntimePaths,
)
from sase.integrations._daemon_lifecycle_values import int_value


def inspect_daemon(
    args: argparse.Namespace,
    *,
    runtime_paths_from_args: Callable[
        [argparse.Namespace], DaemonRuntimePaths
    ] = runtime_paths_from_args,
    host_identity_from_env: Callable[[], str] = host_identity_from_env,
    process_is_live: Callable[[int], bool] = process_is_live,
    executable_matches_metadata: Callable[[int, dict[str, Any]], bool] | None = None,
    metadata_reader: Callable[[Path], dict[str, Any] | str | None] | None = None,
    health_rpc: Callable[[Path], dict[str, Any]] | None = None,
) -> DaemonInspection:
    """Inspect daemon metadata first, then optional local health RPC."""
    paths = runtime_paths_from_args(args)
    read = metadata_reader or read_metadata
    metadata_result = read(paths.metadata_path)
    if metadata_result is None:
        if paths.lock_path.exists():
            lock_held = lock_file_is_held(paths.lock_path)
            if lock_held is True:
                return DaemonInspection(
                    state="conflict",
                    paths=paths,
                    message=(
                        f"daemon lock file exists at {paths.lock_path} and is held, "
                        f"but ownership metadata is missing at {paths.metadata_path}"
                    ),
                )
            if lock_held is None:
                return DaemonInspection(
                    state="incompatible",
                    paths=paths,
                    message=(
                        f"daemon lock file exists at {paths.lock_path}, but ownership "
                        "could not be checked and metadata is missing"
                    ),
                )
            return DaemonInspection(
                state="stale",
                paths=paths,
                message=(
                    f"stale daemon lock file exists at {paths.lock_path} without "
                    f"ownership metadata at {paths.metadata_path}"
                ),
            )
        return DaemonInspection(
            state="stopped",
            paths=paths,
            message=f"no ownership metadata at {paths.metadata_path}",
        )
    if isinstance(metadata_result, str):
        lock_held = lock_file_is_held(paths.lock_path)
        if lock_held is True:
            return DaemonInspection(
                state="conflict",
                paths=paths,
                message=f"{metadata_result}; daemon lock is currently held",
            )
        if lock_held is False:
            return DaemonInspection(
                state="stale",
                paths=paths,
                message=f"{metadata_result}; daemon lock is not held",
            )
        return DaemonInspection(
            state="incompatible",
            paths=paths,
            message=metadata_result,
        )

    metadata = metadata_result
    schema_version = int_value(metadata.get("schema_version"))
    if schema_version != LOCK_SCHEMA_VERSION:
        return DaemonInspection(
            state="incompatible",
            paths=paths,
            metadata=metadata,
            message=f"unsupported lock metadata schema {schema_version}",
        )

    current_host = host_identity_from_env()
    metadata_host = str(metadata.get("hostname") or "")
    if metadata_host != current_host:
        return DaemonInspection(
            state="conflict",
            paths=paths,
            metadata=metadata,
            message=(
                f"metadata belongs to host {metadata_host!r}, "
                f"not this host {current_host!r}"
            ),
        )

    pid = int_value(metadata.get("pid"))
    if pid is None or not process_is_live(pid):
        return DaemonInspection(
            state="stale",
            paths=paths,
            metadata=metadata,
            message=f"metadata pid {pid!r} is not live",
        )
    executable_matcher = executable_matches_metadata or (lambda _pid, _metadata: True)
    if not executable_matcher(pid, metadata):
        return DaemonInspection(
            state="conflict",
            paths=paths,
            metadata=metadata,
            message=(
                f"metadata pid {pid} is live on this host, but its executable "
                "does not match the daemon ownership metadata"
            ),
        )

    rpc_client = health_rpc or try_health_rpc
    rpc = rpc_client(paths.socket_path)
    return DaemonInspection(
        state="running",
        paths=paths,
        metadata=metadata,
        rpc=rpc,
        message=f"daemon metadata points at live pid {pid}",
    )


def read_metadata(path: Path) -> dict[str, Any] | str | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"failed to read ownership metadata {path}: {exc}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return f"failed to parse ownership metadata {path}: {exc}"
    if not isinstance(payload, dict):
        return f"ownership metadata {path} is not a JSON object"
    return payload


def lock_file_is_held(path: Path) -> bool | None:
    try:
        with path.open("r+b") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            except OSError:
                return None
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                return None
            return False
    except FileNotFoundError:
        return False
    except OSError:
        return None


def try_health_rpc(socket_path: Path) -> dict[str, Any]:
    if not socket_path.exists():
        return {
            "available": False,
            "message": f"local socket is not available at {socket_path}",
        }
    try:
        from sase.daemon import client as daemon_client  # type: ignore[import-not-found]
    except ImportError:
        return {
            "available": False,
            "message": "Python local daemon client is not available yet",
        }

    try:
        if hasattr(daemon_client, "LocalDaemonClient"):
            client = daemon_client.LocalDaemonClient(socket_path, timeout=0.5)
            health = client.health(include_capabilities=False)
        elif hasattr(daemon_client, "health"):
            health = daemon_client.health(
                socket_path=socket_path,
                timeout=0.5,
                include_capabilities=False,
            )
            client = None
        else:
            return {
                "available": False,
                "message": "Python local daemon client has no health helper",
            }
    except Exception as exc:
        return {"available": False, "message": str(exc)}

    rpc: dict[str, Any] = {"available": True, "health": health}
    try:
        if client is not None:
            rpc["health"] = client.health(
                include_capabilities=True,
                timeout=2.0,
            )
        else:
            rpc["health"] = daemon_client.health(
                socket_path=socket_path,
                timeout=2.0,
                include_capabilities=True,
            )
        diagnostics = _health_diagnostics_unavailable(rpc["health"])
        if diagnostics is not None:
            rpc["diagnostics"] = diagnostics
    except Exception as exc:
        rpc["diagnostics"] = {
            "available": False,
            "message": str(exc),
        }
    return rpc


def _health_diagnostics_unavailable(health: Any) -> dict[str, Any] | None:
    if not isinstance(health, dict):
        return None
    details = health.get("details")
    if not isinstance(details, dict):
        return None
    diagnostics = details.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    if diagnostics.get("available") is not False:
        return None
    return diagnostics
