"""Typed Python facade for artifact-link publication retry policy."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sase.core.rust import require_rust_binding


@lru_cache(maxsize=1)
def artifact_link_publication_state_wire_schema_version() -> int:
    binding = require_rust_binding(
        "artifact_link_publication_state_wire_schema_version"
    )
    return int(binding())


def artifact_link_publication_record_key(
    *,
    project_key: str,
    role: str,
    repo_root: str,
    remote_url: str,
    upstream: str,
) -> str:
    binding = require_rust_binding("artifact_link_publication_record_key")
    return str(binding(project_key, role, repo_root, remote_url, upstream))


def artifact_link_publication_register_pending(
    current: dict[str, Any] | None,
    observation: dict[str, Any],
    *,
    now: float,
) -> dict[str, Any]:
    binding = require_rust_binding("artifact_link_publication_register_pending")
    return dict(binding(observation, float(now), current))


def artifact_link_publication_due(
    record: dict[str, Any],
    *,
    now: float,
) -> dict[str, Any]:
    binding = require_rust_binding("artifact_link_publication_due")
    return dict(binding(record, float(now)))


def artifact_link_publication_mark_attempt(
    record: dict[str, Any],
    attempt: dict[str, Any],
    *,
    now: float,
) -> dict[str, Any]:
    binding = require_rust_binding("artifact_link_publication_mark_attempt")
    return dict(binding(record, attempt, float(now)))


__all__ = [
    "artifact_link_publication_due",
    "artifact_link_publication_mark_attempt",
    "artifact_link_publication_record_key",
    "artifact_link_publication_register_pending",
    "artifact_link_publication_state_wire_schema_version",
]
