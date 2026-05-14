"""Daemon metadata and health inspection helpers."""

from __future__ import annotations

import argparse
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
    metadata_reader: Callable[[Path], dict[str, Any] | str | None] | None = None,
    health_rpc: Callable[[Path], dict[str, Any]] | None = None,
) -> DaemonInspection:
    """Inspect daemon metadata first, then optional local health RPC."""
    paths = runtime_paths_from_args(args)
    read = metadata_reader or read_metadata
    metadata_result = read(paths.metadata_path)
    if metadata_result is None:
        return DaemonInspection(
            state="stopped",
            paths=paths,
            message=f"no ownership metadata at {paths.metadata_path}",
        )
    if isinstance(metadata_result, str):
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
        if hasattr(daemon_client, "health"):
            health = daemon_client.health(socket_path=socket_path, timeout=0.5)
        elif hasattr(daemon_client, "LocalDaemonClient"):
            health = daemon_client.LocalDaemonClient(socket_path, timeout=0.5).health()
        else:
            return {
                "available": False,
                "message": "Python local daemon client has no health helper",
            }
    except Exception as exc:
        return {"available": False, "message": str(exc)}
    return {"available": True, "health": health}
