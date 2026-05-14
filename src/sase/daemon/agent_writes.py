"""Daemon-backed agent metadata write helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.daemon.client import LocalDaemonClient
from sase.daemon.write_facade import write_or_fallback

AGENT_WRITE_CAPABILITY = "agents.write"
AGENT_WRITE_SCHEMA_VERSION = 1


def _actor() -> dict[str, Any]:
    return {
        "schema_version": AGENT_WRITE_SCHEMA_VERSION,
        "actor_type": "python",
        "name": "sase",
    }


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _stable_key(
    surface: str, payload: dict[str, Any], exports: list[dict[str, Any]]
) -> str:
    digest = hashlib.sha256()
    digest.update(surface.encode("utf-8"))
    digest.update(b"\0")
    digest.update(_stable_json(payload).encode("utf-8"))
    digest.update(b"\0")
    digest.update(_stable_json(exports).encode("utf-8"))
    return f"{surface}:{digest.hexdigest()}"


def atomic_json_export(path: Path, content: str) -> dict[str, Any]:
    return {
        "schema_version": AGENT_WRITE_SCHEMA_VERSION,
        "target_path": str(path),
        "kind": "atomic_json",
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content_utf8": content,
    }


def daemon_agent_write(
    client: LocalDaemonClient,
    surface: str,
    *,
    project_id: str,
    payload: dict[str, Any],
    source_exports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    exports = source_exports or []
    return client.write(
        surface,
        {
            "schema_version": AGENT_WRITE_SCHEMA_VERSION,
            "project_id": project_id or "global",
            "idempotency_key": _stable_key(surface, payload, exports),
            "actor": _actor(),
            "payload": payload,
            "source_exports": exports,
        },
    )


def write_agent_metadata_or_fallback[T](
    surface: str,
    *,
    daemon_writer: Callable[[LocalDaemonClient], T],
    direct_writer: Callable[[], T],
) -> T:
    return write_or_fallback(
        surface,
        required_capability=AGENT_WRITE_CAPABILITY,
        daemon_writer=daemon_writer,
        direct_writer=direct_writer,
    ).value


def project_id_from_bundle(bundle: dict[str, Any]) -> str:
    value = bundle.get("project_name")
    if isinstance(value, str) and value:
        return value
    project_file = bundle.get("project_file")
    if isinstance(project_file, str) and project_file:
        return Path(project_file).stem or "global"
    return "global"


def agent_id(project_id: str, raw_suffix: str | None) -> str:
    return f"agent:{project_id}:{raw_suffix or 'unknown'}"
