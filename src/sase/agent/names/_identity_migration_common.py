"""Shared helpers for historical identity migration internals."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

from sase.agent.names._identity_migration import (
    AgentIdentityMigrationBlocker,
    AgentIdentityMigrationFileAction,
)
from sase.agent.names._identity_migration_types import JsonPayload


def read_json_payload(
    path: Path,
    *,
    required: bool,
    blockers: list[AgentIdentityMigrationBlocker] | None = None,
) -> JsonPayload | None:
    try:
        preimage = path.read_bytes()
    except FileNotFoundError:
        if required and blockers is not None:
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "missing_json", f"missing required JSON file: {path}", str(path)
                )
            )
        return None
    except OSError as exc:
        if blockers is not None:
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "unreadable_json", f"could not read {path}: {exc}", str(path)
                )
            )
        return None
    try:
        data = json.loads(preimage.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if blockers is not None:
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "malformed_json", f"could not parse {path}: {exc}", str(path)
                )
            )
        return None
    if not isinstance(data, dict):
        if blockers is not None:
            blockers.append(
                AgentIdentityMigrationBlocker(
                    "malformed_json", f"{path} must contain a JSON object", str(path)
                )
            )
        return None
    return JsonPayload(path, data, preimage)


def json_bytes(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_action(
    path: Path,
    preimage: bytes,
    postimage: bytes,
    counts: Mapping[str, int],
) -> AgentIdentityMigrationFileAction:
    return AgentIdentityMigrationFileAction(
        "write",
        str(path),
        str(path),
        sha256(preimage),
        sha256(postimage),
        counts_tuple(counts),
        postimage,
    )


def merge_counts(target: dict[str, int], source: Mapping[str, int]) -> None:
    for key, count in source.items():
        if count:
            target[key] = target.get(key, 0) + int(count)


def counts_tuple(counts: Mapping[str, int]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((key, int(value)) for key, value in counts.items() if value))


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
